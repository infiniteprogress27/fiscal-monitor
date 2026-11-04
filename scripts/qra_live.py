#!/usr/bin/env python3
"""QRA 发布日实时抓取 + 与上期逐字红线 (本机跑, 由 AgentHub shell 任务 qra-release-watch 拉起)。

  qra_live.py due [--within 20]       今天(美东)是否有 QRFE / Statement 发布, 距发布 ≤N 分钟才输出 kind
  qra_live.py watch statement|qrfe --until 3600 [--interval 2]
                                      轮询财政部「最新文件」页直到本季文件出现 → 抓正文 → 与上季红线
                                      → 写 data/us/qra_live/<季>/<kind>.json (锚) + 本机 PDF 副本 → 推送 → 触发重建
  qra_live.py redo statement 2026Q4   不轮询, 直接按已知链接重抓重算(补救/测试)

季度口径与 qra_docs.json 一致: refunding 所在日历季(11月=Q4)。上季链接取自 qra_docs.json。
Statement 8:30 ET、QRFE 15:00 ET 发布; 时间以 events.jsonl 的 qra_stmt- / qra_est- 为准。
只用标准库。
"""
import difflib, html, json, os, re, subprocess, sys, time, urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
DATA = os.path.join(ROOT, 'data', 'us')
LIVE = os.path.join(DATA, 'qra_live')
LOCAL = os.path.expanduser('~/agenthub/workspace/outputs/qra')  # PDF 等大文件只放本机, 不进公开仓库
TRE = 'https://home.treasury.gov'
RECENT = TRE + '/policy-issues/financing-the-government/quarterly-refunding/most-recent-quarterly-refunding-documents'
ET = ZoneInfo('America/New_York')
KIND = {'statement': ('qra_stmt-', 'Policy Statement', (8, 30)),
        'qrfe': ('qra_est-', 'Financing Estimates', (15, 0))}
PR_LIST = TRE + '/news/press-releases'
PR_TITLE = {'statement': 'Quarterly Refunding Statement', 'qrfe': 'Treasury Announces Marketable Borrowing Estimates'}
ORD = {1: '1st', 2: '2nd', 3: '3rd', 4: '4th'}
NOPROXY = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get(url, timeout=15, binary=False):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (fiscal-monitor)', 'Cache-Control': 'no-cache'})
    for opener in (NOPROXY, urllib.request.build_opener()):  # 直连优先, 失败再走系统代理
        try:
            with opener.open(req, timeout=timeout) as r:
                b = r.read()
                return b if binary else b.decode('utf-8', 'ignore')
        except Exception as e:
            err = e
    raise err


def log(*a):
    print(time.strftime('%H:%M:%S'), *a, flush=True)


def quarter_of(d):  # date -> "2026Q4"
    return f'{d.year}Q{(d.month - 1) // 3 + 1}'


def prev_quarter(q):
    y, n = int(q[:4]), int(q[-1])
    return f'{y - 1}Q4' if n == 1 else f'{y}Q{n - 1}'


def label(q):  # "2026Q4" -> "2026 - 4th Quarter"
    return f'{q[:4]} - {ORD[int(q[-1])]} Quarter'


def events():
    p = os.path.join(DATA, 'events.jsonl')
    return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]


def release_today(kind):
    pre, _, (hh, mm) = KIND[kind]
    today = datetime.now(ET).date().isoformat()
    for e in events():
        if e['id'].startswith(pre) and e['date'] == today and e.get('status') != 'cancelled':
            return datetime.now(ET).replace(hour=hh, minute=mm, second=0, microsecond=0)
    return None


def links(doc):
    out = []
    for h, t in re.findall(r'<a[^>]+href="?([^"\s>]+)"?[^>]*>(.*?)</a>', doc, re.S):
        t = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', t))).replace('​', '').strip()
        if t:
            out.append((t, h if h.startswith('http') else TRE + h))
    return out


def body_blocks(doc):
    """新闻稿正文 → 段落列表; 表格每行一段 "a | b | c"。"""
    i = doc.find('field--name-field-news-body')
    seg = doc[i:] if i >= 0 else doc
    for end in ('field--name-body', '>Latest News<', 'Latest News'):  # 正文后是站点页脚导航
        j = seg.find(end)
        if j > 0:
            seg = seg[:j]
    blocks = []
    for m in re.finditer(r'<(p|li|h[1-6]|tr)\b[^>]*>(.*?)</\1>', seg, re.S):
        tag, inner = m.group(1), m.group(2)
        if tag == 'tr':
            cells = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', '', c))).strip()
                     for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', inner, re.S)]
            t = ' | '.join(cells)
        else:
            if tag == 'p' and '<li' in inner:
                continue
            t = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', inner))).strip()
            if tag == 'li':
                t = '• ' + t
        t = t.replace(' ', ' ').replace('‑', '-').replace('​', '').strip()
        if t and not t.startswith('###'):
            blocks.append(t)
    return blocks


def tokens(blocks):
    out = []
    for b in blocks:
        out += re.findall(r'\S+', b) + ['¶']
    return out


def redline(old, new):
    """逐词红线 → (html, 纯文本[-删-]{+增+}, 统计)。"""
    a, b = tokens(old), tokens(new)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    h, t, n = [], [], {'ins': 0, 'del': 0}

    def emit(ws, cls=None):
        s = ' '.join(ws)
        if cls is None:
            h.append(html.escape(s).replace('¶', '<br><br>')); t.append(s)
        else:
            tag = 'ins' if cls == 'ins' else 'del'
            n[cls] += len([w for w in ws if w != '¶'])
            h.append(f'<{tag}>{html.escape(s).replace("¶", "¶<br>")}</{tag}>')
            t.append(('{+' if cls == 'ins' else '[-') + s + ('+}' if cls == 'ins' else '-]'))

    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            emit(a[i1:i2])
        else:
            if i2 > i1: emit(a[i1:i2], 'del')
            if j2 > j1: emit(b[j1:j2], 'ins')
    txt = ' '.join(t).replace(' ¶ ', '\n\n').replace('¶', '\n\n')
    return ' '.join(h), txt, {**n, 'similarity': round(sm.ratio(), 3)}


def sentences(blocks, with_pid=False):
    """段落 → [(小节标题, 句子)] (with_pid 时为 (小节, 段号, 句子)); 全大写短段视为小节标题, 表格行整行算一句。"""
    out, sec = [], ''
    for pid, b in enumerate(blocks):
        if b.isupper() and len(b) < 80:
            sec = b; continue
        b = b.lstrip('• ')
        if ' | ' in b:
            parts = [b]
        else:  # 缩写不断句
            t = re.sub(r'\b(U\.S|p\.m|a\.m|No|Mr|Ms|Dr|Inc|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.', lambda m: m.group(1) + '\x00', b)
            parts = [x.replace('\x00', '.') for x in re.split(r'(?<=[.;:])\s+(?=[A-Z$(])', t)]
        out += [((sec, pid, x.strip()) if with_pid else (sec, x.strip())) for x in parts if x.strip()]
    return out


def word_html(a, b):
    aw, bw = a.split(), b.split()
    sm = difflib.SequenceMatcher(None, aw, bw, autojunk=False)
    o = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            o.append(html.escape(' '.join(aw[i1:i2])))
        else:
            if i2 > i1: o.append('<del>' + html.escape(' '.join(aw[i1:i2])) + '</del>')
            if j2 > j1: o.append('<ins>' + html.escape(' '.join(bw[j1:j2])) + '</ins>')
    return ' '.join(o)


def redline_sent_html(old, new):
    """按句对齐的全文红线: 未改句照常显示, 改动句内逐词标, 整句增删整句标; 表格行整行对齐; 保留小节与段落。"""
    a, b = sentences(old, True), sentences(new, True)
    sm = difflib.SequenceMatcher(None, [x[2] for x in a], [x[2] for x in b], autojunk=False)
    items = []  # (小节, 段键, html, 是否表格行)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            items += [(y[0], ('n', y[1]), html.escape(y[2]), ' | ' in y[2]) for y in b[j1:j2]]
        elif op == 'replace':
            for x, y in align_chunk(a[i1:i2], b[j1:j2], key=lambda t: t[2]):
                if x and y:
                    items.append((y[0], ('n', y[1]), word_html(x[2], y[2]), ' | ' in y[2]))
                elif x:
                    items.append((x[0], ('o', x[1]), '<del>' + html.escape(x[2]) + '</del>', ' | ' in x[2]))
                else:
                    items.append((y[0], ('n', y[1]), '<ins>' + html.escape(y[2]) + '</ins>', ' | ' in y[2]))
        else:
            items += [(x[0], ('n', b[j1][1]) if j2 > j1 else ('o', x[1]), '<del>' + html.escape(x[2]) + '</del>', ' | ' in x[2]) for x in a[i1:i2]]
            items += [(y[0], ('n', y[1]), '<ins>' + html.escape(y[2]) + '</ins>', ' | ' in y[2]) for y in b[j1:j2]]
    out, sec, key = [], None, None
    for sc, k, h, tr in items:
        if sc != sec:
            if key is not None: out.append('</p>')
            out.append(f'<h5>{html.escape(sc or "")}</h5>' if sc else ''); sec, key = sc, None
        if tr:
            if key is not None: out.append('</p>'); key = None
            out.append(f'<div class="rtr">{h}</div>')
            continue
        if k != key:
            if key is not None: out.append('</p>')
            out.append('<p>'); key = k
        else:
            out.append(' ')
        out.append(h)
    if key is not None: out.append('</p>')
    return ''.join(out)


def align_chunk(olds, news, key=lambda x: x):
    """不等长替换块内按相似度顺序配对: 返回 [(old|None, new|None)]; 相似度≥0.6 视为同一句改写。"""
    out, j = [], 0
    for o in olds:
        best = None
        for k in range(j, len(news)):
            if difflib.SequenceMatcher(None, key(o), key(news[k]), autojunk=False).ratio() >= 0.6:
                best = k; break
        if best is None:
            out.append((o, None)); continue
        out += [(None, n) for n in news[j:best]] + [(o, news[best])]
        j = best + 1
    return out + [(None, n) for n in news[j:]]


def word_md(a, b):
    """两句逐词 → Slack markdown: ~~删~~ **增**。"""
    aw, bw = a.split(), b.split()
    sm = difflib.SequenceMatcher(None, aw, bw, autojunk=False)
    o = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            o.append(' '.join(aw[i1:i2]))
        else:
            if i2 > i1: o.append('~~' + ' '.join(aw[i1:i2]) + '~~')
            if j2 > j1: o.append('**' + ' '.join(bw[j1:j2]) + '**')
    return ' '.join(o)


def slack_redline(old, new):
    """逐句红线(只列有改动的句子, 按小节分组; 整句删=~~句~~, 整句增=**句**)。"""
    a, b = sentences(old), sentences(new)
    sm = difflib.SequenceMatcher(None, [x[1] for x in a], [x[1] for x in b], autojunk=False)
    rows = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == 'equal':
            continue
        sec = (b[j1][0] if j2 > j1 else a[i1][0]) or '开头'
        if op == 'replace':
            olds, news = a[i1:i2], b[j1:j2]
            for x, y in align_chunk(olds, news, key=lambda t: t[1]):
                if x and y:
                    rows.append((y[0] or sec, word_md(x[1], y[1])))
                elif x:
                    rows.append((x[0] or sec, '~~' + x[1] + '~~'))
                else:
                    rows.append((y[0] or sec, '**' + y[1] + '**'))
        elif op == 'delete':
            rows += [(a[i][0] or sec, '~~' + a[i][1] + '~~') for i in range(i1, i2)]
        else:
            rows += [(b[j][0] or sec, '**' + b[j][1] + '**') for j in range(j1, j2)]
    out, last = [], None
    for sec, line in rows:
        if sec != last:
            out.append(f'\n*{sec}*'); last = sec
        out.append('• ' + line)
    return '\n'.join(out).strip()


QTR_END = {'March': 1, 'June': 2, 'September': 3, 'December': 4}


def qrfe_numbers(blocks):
    """QRFE 新闻稿 → {季: (私人净融资bn, 期末TGA bn)} (只取 expects to borrow 的两句)。"""
    out = {}
    for b in blocks:
        m = re.search(r'During the \w+\W+(\w+) (\d{4}) quarter, Treasury expects to borrow \$([\d,.]+) (billion|trillion).*?'
                      r'cash balance of \$([\d,.]+) (billion|trillion)', b)
        if m and m.group(1) in QTR_END:
            v = lambda x, u: round(float(x.replace(',', '')) * (1000 if u == 'trillion' else 1))
            out[f'{m.group(2)}Q{QTR_END[m.group(1)]}'] = (v(m.group(3), m.group(4)), v(m.group(5), m.group(6)))
    return out


def update_qra_history(nums, src):
    p = os.path.join(DATA, 'qra_history.json')
    d = json.load(open(p, encoding='utf-8'))
    rows = {r['q']: r for r in d['rows']}
    for q, (bor, tga) in nums.items():
        r = rows.setdefault(q, {'q': q})
        r.update({'borrowing': bor, 'tga_end': tga, 'note': src})
    d['rows'] = sorted(rows.values(), key=lambda r: r['q'])
    json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return p


def git(*a):
    return subprocess.run(['git', '-C', ROOT, *a], capture_output=True, text=True)


def publish(q, kind):
    rel = os.path.relpath(os.path.join(LIVE, q), ROOT)
    git('pull', '-q', '--rebase', 'origin', 'main')
    git('add', rel)
    if kind == 'qrfe':
        git('add', 'data/us/qra_history.json')
    r = git('commit', '-q', '-m', f'qra_live: {q} {kind} 抓取与红线\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>')
    if r.returncode:
        log('commit:', (r.stdout + r.stderr).strip()[:200]); return
    for k in range(3):
        if git('push', '-q').returncode == 0:
            break
        git('pull', '-q', '--rebase', 'origin', 'main')
    subprocess.run(['gh', 'workflow', 'run', 'update-dashboard', '-R', 'infiniteprogress27/fiscal-monitor', '-f', 'mode=daily'],
                   capture_output=True)
    log('pushed + rebuild triggered')


def pdf_text(fn):
    """PDF → 同名 .txt, 每页以 "=== p.N ===" 分隔 (分析任务读文本; 本机 Read 工具读不了多页 PDF)。需 .venv 里的 pypdf。"""
    try:
        from pypdf import PdfReader
    except ImportError:
        log('pypdf missing, no text for', fn); return None
    r = PdfReader(fn)
    t = ''.join(f'\n\n=== p.{i + 1} ===\n' + (pg.extract_text() or '') for i, pg in enumerate(r.pages))
    out = fn[:-4] + '.txt'
    open(out, 'w', encoding='utf-8').write(t)
    return out


def process(kind, q, url, page_links, fetched_at, tries):
    doc = get(url)
    new = body_blocks(doc)
    docs = json.load(open(os.path.join(DATA, 'qra_docs.json'), encoding='utf-8')).get('quarters', {})
    pq = prev_quarter(q)
    purl = (docs.get(pq) or {}).get(kind)
    old = body_blocks(get(purl)) if purl else []
    _, rt, st = redline(old, new)
    rh = redline_sent_html(old, new)
    os.makedirs(os.path.join(LIVE, q), exist_ok=True)
    os.makedirs(os.path.join(LOCAL, q), exist_ok=True)
    # 同页其他本期文件: TBAC 讨论材料(Charges) / 推荐融资表 / TBAC 报告 / 纪要 ……
    tag = label(q).split(' - ')[0]
    extra = {}
    for t, h in page_links:
        low = (t + h).lower()
        if h.lower().endswith('.pdf') or 'press-releases' in h:
            if any(k in low for k in ('charge', 'tbac', 'financing table', 'presentation', 'minutes', 'report')):
                extra[t] = h
    pdfs = {}
    for t, h in extra.items():
        if h.lower().endswith('.pdf'):
            name = h.rsplit('/', 1)[-1]
            dm = re.search(r'(\d{2})(\d{2})(\d{4})\.pdf$', name)  # 推荐融资表按日期 MMDDYYYY 命名
            mine = f'Q{q[-1]}{q[:4]}' in name or (dm and quarter_of(datetime(int(dm.group(3)), int(dm.group(1)), 1)) == q)
            if not mine:  # 「最新文件」页上还挂着别季的文件, 不混进本季
                continue
            fn = os.path.join(LOCAL, q, re.sub(r'[^\w.-]+', '_', name))
            try:
                open(fn, 'wb').write(get(h, timeout=60, binary=True)); pdfs[t] = fn
                pdf_text(fn)
            except Exception as e:
                log('pdf fail', h, e)
    out = {'sample': False, 'quarter': q, 'kind': kind, 'url': url, 'prev_quarter': pq, 'prev_url': purl,
           'fetched_at': fetched_at, 'tries': tries, 'paragraphs': new, 'prev_paragraphs': old,
           'redline_html': rh, 'stats': st, 'page_docs': extra,
           'analysis': None, 'tbac_summary': None, 'analyzed_at': None}
    p = os.path.join(LIVE, q, f'{kind}.json')
    if os.path.exists(p):  # 重抓时保留已写的分析
        old_j = json.load(open(p, encoding='utf-8'))
        for k in ('analysis', 'tbac_summary', 'analyzed_at'):
            out[k] = old_j.get(k)
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(LOCAL, q, f'{kind}_redline.txt'), 'w', encoding='utf-8').write(rt)
    open(os.path.join(LOCAL, q, f'{kind}_redline_slack.md'), 'w', encoding='utf-8').write(slack_redline(old, new))
    if kind == 'qrfe':
        nums = qrfe_numbers(new)
        if nums:
            update_qra_history(nums, f'{fetched_at[:10]} QRFE')
            log('qra_history <-', nums)
    json.dump({'quarter': q, 'kind': kind, 'json': p, 'redline_txt': os.path.join(LOCAL, q, f'{kind}_redline.txt'),
               'redline_slack': os.path.join(LOCAL, q, f'{kind}_redline_slack.md'),
               'pdfs': pdfs, 'page_docs': extra, 'at': fetched_at},
              open(os.path.join(LOCAL, 'pending.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f'{kind} {q}: {len(new)}段 vs {pq} {len(old)}段 · 增{st["ins"]}词 删{st["del"]}词 · 相似度{st["similarity"]} · PDF {len(pdfs)}')
    return p


def wait_pdfs(kind, q, url, got, tries, until=1800):
    """红线先推; TBAC 讨论材料 PDF 若还没挂到「最新文件」页, 每 5 秒再看, 拿到后重写本机 PDF 与 pending.json。"""
    tag = f'Q{q[-1]}{q[:4]}'
    t0 = time.time()
    while time.time() - t0 < until:
        try:
            page = links(get(RECENT + f'?t={int(time.time())}', timeout=10))
            if any(tag in h and 'charge' in h.lower() for t, h in page):
                process(kind, q, url, page, got, tries)
                log('TBAC PDFs ready'); return True
        except Exception as e:
            log('pdf poll err', e)
        time.sleep(5)
    log('TBAC PDFs not found in', until, 's; analysis runs without them'); return False


def watch(kind, until, interval):
    t0 = time.time()
    rel = release_today(kind)
    q = quarter_of(rel or datetime.now(ET))
    want = f'{KIND[kind][1]}: {label(q)}'
    log('watching for', repr(want))
    tries = 0
    while True:
        tries += 1
        try:
            page = links(get(RECENT + f'?t={int(time.time())}', timeout=10))
            hit = next((h for t, h in page if t.startswith(want)), None)
            if not hit:  # 「最新文件」页可能比新闻稿晚更新: 同时看新闻稿列表(排除已知各季链接)
                known = {u.rstrip('/') for v in json.load(open(os.path.join(DATA, 'qra_docs.json'))).get('quarters', {}).values()
                         for u in v.values() if u}
                pr = links(get(PR_LIST + f'?t={int(time.time())}', timeout=10))
                hit = next((h for t, h in pr if t.startswith(PR_TITLE[kind]) and h.rstrip('/') not in known
                            and '/press-releases/sb' in h), None)
            if hit:
                got = datetime.now(ET).isoformat(timespec='seconds')
                log('found', hit, 'after', tries, 'tries')
                for k in range(10):
                    try:
                        process(kind, q, hit, page, got, tries); break
                    except Exception as e:
                        log('process retry', e); time.sleep(3)
                else:
                    return 1
                publish(q, kind)
                if kind == 'statement':
                    wait_pdfs(kind, q, hit, got, tries)
                return 0
        except Exception as e:
            if tries % 30 == 1: log('poll err', e)
        if time.time() - t0 > until:
            log('not published after', tries, 'tries'); return 2
        time.sleep(interval)


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'due':
        w = int(a[a.index('--within') + 1]) if '--within' in a else 20
        now = datetime.now(ET)
        for k in KIND:
            r = release_today(k)
            if r and -10 <= (r - now).total_seconds() / 60 <= w:  # 发布前 w 分钟 ~ 发布后 10 分钟
                if not os.path.exists(os.path.join(LIVE, quarter_of(r), f'{k}.json')):  # 已抓过不重复
                    print(k)
    elif a[0] == 'watch':
        until = int(a[a.index('--until') + 1]) if '--until' in a else 3600
        iv = float(a[a.index('--interval') + 1]) if '--interval' in a else 2
        sys.exit(watch(a[1], until, iv))
    elif a[0] == 'redo':
        kind, q = a[1], a[2]
        page = links(get(RECENT))
        want = f'{KIND[kind][1]}: {label(q)}'
        url = next((h for t, h in page if t.startswith(want)), None)
        if not url:
            url = json.load(open(os.path.join(DATA, 'qra_docs.json'))).get('quarters', {}).get(q, {}).get(kind)
        process(kind, q, url, page, datetime.now(ET).isoformat(timespec='seconds'), 0)
        if '--publish' in a: publish(q, kind)
