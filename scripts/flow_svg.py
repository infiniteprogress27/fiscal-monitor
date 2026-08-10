#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
flow_svg.py — 预算周期通关图
结构为固定模板(节点文字与勾稽线不随年份变), 年度实例只提供 {node_id: state}。
state: done(蓝) / active(绿) / pending(灰空心), 尾缀"!"=逾期/风险提示(非颜色标记)。
"""
import html as _h

esc = lambda s: _h.escape(str(s))

LANES = [("总统预算", 46), ("预算决议", 142), ("和解·授权", 240), ("拨款", 340), ("补充拨款", 432), ("资金现实", 522)]
_CX = lambda c: 128 + 114 * c

NODES = [  # (id, lane, col, 固定文字, 用·分行)
    ("pb1", 0, 0, "OMB Spring·Guidance"), ("pb2", 0, 1, "机构预算·请求"),
    ("pb3", 0, 2, "OMB·Passback"), ("pb4", 0, 3, "总统预算·提交"), ("pb5", 0, 6, "MSR·年中修订"),
    ("b0", 1, 2, "CBO预算·经济展望"), ("b1", 1, 3, "听证与·views&est."),
    ("b2", 1, 4, "起草预算·决议"), ("b3", 1, 5, "两院分别·投票"),
    ("b4", 1, 6, "两院协调·统一"), ("b5", 1, 7, "共同决议·302(a)/指令"), ("b6", 1, 8, "Deeming·决议(替代)"),
    ("r1", 2, 7, "和解指令·下达"), ("r2", 2, 8, "授权委员会·按指令立法"), ("r3", 2, 9, "打包·Byrd·51票签署"),
    ("a1", 3, 2, "小组听证·分析PB"), ("a2", 3, 3, "302(b)·摊派12组"),
    ("a3", 3, 4, "markup·全委审议"), ("a4", 3, 5, "众院·floor"),
    ("a5", 3, 6, "参院floor·(60票)"), ("a6", 3, 7, "两院协调·打包"), ("a7", 3, 8, "拨款成法·(10/1前)"),
    ("sp1", 4, 4, "白宫补充·请求"), ("sp2", 4, 5, "两院·审议"), ("sp3", 4, 6, "成法·(紧急指定)"),
    ("f1", 5, 7, "CR·临时拨款"), ("f2", 5, 8, "CR到期·节点"), ("f3", 5, 9, "再CR/全年案·否则关门"),
]

ARROWS = [  # (from, to, style, label, route)  route: seq / vert / cor:y
    ("pb1", "pb2", "solid", "", "seq"), ("pb2", "pb3", "solid", "", "seq"),
    ("pb3", "pb4", "solid", "", "seq"), ("pb4", "pb5", "solid", "", "seq"),
    ("pb4", "b1", "dash", "提交国会", "vert"),
    ("b0", "b1", "dash", "", "seq"), ("b1", "b2", "solid", "", "seq"),
    ("b2", "b3", "solid", "", "seq"), ("b3", "b4", "solid", "", "seq"), ("b4", "b5", "solid", "", "seq"),
    ("b3", "b6", "dash", "未达成", "cor:178"),
    ("b5", "r1", "solid", "和解指令", "vert"),
    ("b5", "a2", "solid", "302(a)→302(b)", "cor:192"),
    ("b6", "a2", "dash", "替代分配", "cor:206"),
    ("a1", "a2", "solid", "", "seq"), ("a2", "a3", "solid", "", "seq"),
    ("a3", "a4", "solid", "", "seq"), ("a4", "a5", "solid", "", "seq"),
    ("a5", "a6", "solid", "", "seq"), ("a6", "a7", "solid", "", "seq"),
    ("sp1", "sp2", "solid", "", "seq"), ("sp2", "sp3", "solid", "", "seq"),
    ("a7", "f1", "dash", "未按期", "cor:482"),
    ("f1", "f2", "solid", "", "seq"), ("f2", "f3", "solid", "", "seq"),
    ("r1", "r2", "solid", "", "seq"), ("r2", "r3", "solid", "", "seq"),
]

_STYLE = (
    "<style>"
    ".fl-lbl{font:600 11px 'IBM Plex Sans','Noto Sans SC',sans-serif;fill:#5D6B76}"
    ".fn-t{font:10.5px 'IBM Plex Sans','Noto Sans SC',sans-serif;text-anchor:middle}"
    ".al{font:9.5px 'IBM Plex Mono',monospace;fill:#5D6B76}"
    ".n-done{fill:#DCE7F2;stroke:#2B5B8A}.t-done{fill:#2B5B8A}"
    ".n-active{fill:#E3EFE6;stroke:#0E5A45;stroke-width:2}.t-active{fill:#0E5A45;font-weight:600}"
    ".n-pending{fill:#FFFFFF;stroke:#C9CFCC}.t-pending{fill:#8A97A1}"
    ".ln{stroke:#8A97A1;fill:none;stroke-width:1.3}.ln-d{stroke-dasharray:5 4}"
    "</style>"
)


def render(states):
    pos = {nid: (_CX(c), LANES[ln][1]) for nid, ln, c, _ in NODES}
    NW, NH = 104, 40
    out = ['<svg viewBox="0 0 1215 576" style="width:100%;height:auto" xmlns="http://www.w3.org/2000/svg">',
           '<defs><marker id="ah" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto">'
           '<path d="M0,0 L6,3 L0,6 z" fill="#8A97A1"/></marker></defs>', _STYLE]
    for name, y in LANES:
        out.append(f'<text class="fl-lbl" x="8" y="{y+4}">{name}</text>')
        out.append(f'<line x1="70" y1="{y}" x2="1205" y2="{y}" stroke="#EDEFEA"/>')
    for a, b, style, label, route in ARROWS:
        (x1, y1), (x2, y2) = pos[a], pos[b]
        cls = "ln ln-d" if style == "dash" else "ln"
        if route == "seq":
            d = f"M{x1+NW/2},{y1} L{x2-NW/2},{y2}"
            lx, ly = (x1 + x2) / 2, y1 - 6
        elif route == "vert":
            d = f"M{x1},{y1+NH/2} L{x2},{y2-NH/2}"
            lx, ly = x1 + 8, (y1 + y2) / 2
        else:
            cy = int(route.split(":")[1])
            xo = x1 - 26 if x2 < x1 else x1 + 26
            d = f"M{xo},{y1+NH/2} L{xo},{cy} L{x2},{cy} L{x2},{y2-NH/2}"
            lx, ly = (xo + x2) / 2, cy - 4
        out.append(f'<path class="{cls}" d="{d}" marker-end="url(#ah)"/>')
        if label:
            out.append(f'<text class="al" x="{lx}" y="{ly}" text-anchor="middle">{esc(label)}</text>')
    for nid, ln, c, label in NODES:
        x, y = pos[nid]
        st = str(states.get(nid, "pending"))
        flag = st.endswith("!")
        st = st.rstrip("!")
        out.append(f'<rect class="n-{st}" x="{x-NW/2}" y="{y-NH/2}" width="{NW}" height="{NH}" rx="7"/>')
        parts = label.split("·")
        if len(parts) == 1:
            out.append(f'<text class="fn-t t-{st}" x="{x}" y="{y+4}">{esc(parts[0])}</text>')
        else:
            out.append(f'<text class="fn-t t-{st}" x="{x}" y="{y-2}">{esc(parts[0])}</text>')
            out.append(f'<text class="fn-t t-{st}" x="{x}" y="{y+11}">{esc(parts[1])}</text>')
        if flag:
            out.append(f'<circle cx="{x+NW/2-4}" cy="{y-NH/2+4}" r="7" fill="#16222C"/>'
                       f'<text x="{x+NW/2-4}" y="{y-NH/2+7.5}" text-anchor="middle" '
                       f'style="font:700 10px monospace;fill:#fff">!</text>')
    out.append('<g transform="translate(70,562)">'
               '<rect class="n-done" x="0" y="-11" width="14" height="14" rx="3"/>'
               '<text class="fn-t t-done" x="46" y="0">已完成</text>'
               '<rect class="n-active" x="86" y="-11" width="14" height="14" rx="3"/>'
               '<text class="fn-t t-active" x="134" y="0">进行中</text>'
               '<rect class="n-pending" x="176" y="-11" width="14" height="14" rx="3"/>'
               '<text class="fn-t t-pending" x="224" y="0">待进行</text>'
               '<circle cx="268" cy="-4" r="7" fill="#16222C"/>'
               '<text x="268" y="-0.5" text-anchor="middle" style="font:700 10px monospace;fill:#fff">!</text>'
               '<text class="fn-t" x="326" y="0" style="fill:#5D6B76">逾期/风险</text></g>')
    out.append("</svg>")
    return '<div style="overflow-x:auto;margin:8px 0">' + "".join(out) + "</div>"
