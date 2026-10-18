# -*- coding: utf-8 -*-
"""构建脚本：把 content/*.json、template.html、assets/ 打包成自包含的 dist/index.html。

用法（在仓库根目录）：
    python build.py                       # 用 content/00-event.json 里的大会日期
    python build.py --date 2027-09-20     # 临时覆盖日期，不必改文件
    python build.py --open                # 构建完自动用浏览器打开

文案里的 {year} {date} {venue} 等占位符会在构建时替换成 content/00-event.json 里的值。
"""
import argparse
import base64
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CONTENT_DIR = os.path.join(ROOT, 'content')
TPL = os.path.join(ROOT, 'template.html')
CSS = os.path.join(ROOT, 'assets', 'style.css')
FONT = os.path.join(ROOT, 'assets', 'zpix.woff2')
LOGO = os.path.join(ROOT, 'assets', 'logo.png')
DIST = os.path.join(ROOT, 'dist')
OUT = os.path.join(DIST, 'index.html')

CSS_LINK = '<link rel="stylesheet" href="./assets/style.css">'
CFG_TAG = re.compile(r'<script id="cfg">[\s\S]*?</script>')
TITLE_TAG = re.compile(r'<title>.*?</title>')

# 页面运行时才替换的占位符（{n} {num} {name} {done} {total}），构建时原样保留
RUNTIME_KEYS = {'n', 'num', 'name', 'done', 'total'}
VAR_RE = re.compile(r'\{(\w+)\}')

problems = []


def rel(path):
    return os.path.relpath(path, ROOT).replace('\\', '/')


def fail(msg):
    print('[x] %s' % msg)
    return 1


def warn(msg):
    problems.append(msg)
    print('[!] %s' % msg)


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def data_uri(path, mime):
    with open(path, 'rb') as f:
        return 'data:%s;base64,%s' % (mime, base64.b64encode(f.read()).decode('ascii'))


def load_content():
    """读取 content/*.json，按文件名顺序合并；顶层键重复直接报错。"""
    files = sorted(glob.glob(os.path.join(CONTENT_DIR, '*.json')))
    if not files:
        raise SystemExit(fail('content/ 里没有 json 文件'))

    cfg, owner = {}, {}
    for path in files:
        name = rel(path)
        try:
            data = json.loads(read_text(path))
        except json.JSONDecodeError as e:
            raise SystemExit(fail(
                '%s 第 %d 行第 %d 列 JSON 格式错误：%s\n'
                '    常见原因：漏了/多了逗号、引号没成对、JSON 里不能写 // 注释' % (name, e.lineno, e.colno, e.msg)))
        if not isinstance(data, dict):
            raise SystemExit(fail('%s 的最外层必须是 { } 包裹的对象' % name))
        for key, value in data.items():
            if key in cfg:
                raise SystemExit(fail('顶层键 "%s" 在 %s 和 %s 里重复了' % (key, owner[key], name)))
            cfg[key] = value
            owner[key] = name
    return cfg


def parse_date(text):
    """支持 2026-10-14 / 2026/10/14 / 2026.10.14 / 2026年10月14日。"""
    s = re.sub(r'\s*年\s*', '-', str(text).strip())
    s = re.sub(r'\s*月\s*', '-', s)
    s = re.sub(r'\s*日\s*$', '', s).replace('/', '-').replace('.', '-')
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def build_vars(event):
    """由 00-event.json 派生可用占位符：{year} {date} {dateCn} {weekday} …"""
    if not isinstance(event, dict):
        raise SystemExit(fail('content/00-event.json 里需要一个 event 对象'))

    vars_ = {k: v for k, v in event.items() if isinstance(v, (str, int, float))}
    day = parse_date(event.get('date', ''))
    if day is None:
        raise SystemExit(fail('event.date 不是合法日期：%r（示例：2026-10-14）' % event.get('date')))

    vars_.update({
        'year': day.year,
        'month': day.month,
        'day': day.day,
        'date': '%d.%02d.%02d' % (day.year, day.month, day.day),
        'dateIso': day.strftime('%Y-%m-%d'),
        'dateCn': '%d年%d月%d日' % (day.year, day.month, day.day),
        'weekday': '周' + '一二三四五六日'[day.weekday()],
    })
    return vars_


def fill(node, vars_, missing):
    """递归替换字符串里的 {占位符}，未知的收集起来提示。"""
    if isinstance(node, str):
        def rep(m):
            key = m.group(1)
            if key in vars_:
                return str(vars_[key])
            if key not in RUNTIME_KEYS:
                missing.add(key)
            return m.group(0)
        return VAR_RE.sub(rep, node)
    if isinstance(node, list):
        return [fill(i, vars_, missing) for i in node]
    if isinstance(node, dict):
        return {k: fill(v, vars_, missing) for k, v in node.items()}
    return node


def fill_text(text, vars_):
    """替换模板里静态兜底文案的占位符；不认识的保持原样（多是运行时占位符）。"""
    return VAR_RE.sub(lambda m: str(vars_[m.group(1)]) if m.group(1) in vars_ else m.group(0), text)


def validate(cfg):
    stages = cfg.get('stages')
    if not isinstance(stages, list) or not stages:
        raise SystemExit(fail('content/04-stages.json 的 stages 不能为空'))
    for i, s in enumerate(stages, 1):
        if not isinstance(s, dict) or not s.get('name'):
            warn('第 %d 个环节缺少 name 字段' % i)
            continue
        if s.get('fullPage') and not s.get('gallery'):
            warn('环节「%s」开了 fullPage，但没写 gallery' % s['name'])
        if s.get('aboutPage') and not s.get('about'):
            warn('环节「%s」开了 aboutPage，但没写 about' % s['name'])
        if s.get('gamePage') and not s.get('games'):
            warn('环节「%s」开了 gamePage，但没写 games' % s['name'])


def stats(cfg):
    stages = cfg.get('stages') or []
    shows = sum(len(s.get('gallery') or []) for s in stages)
    games = sum(len(s.get('games') or []) for s in stages)
    return '环节 %d 个 · 节目 %d 个 · 游戏 %d 个' % (len(stages), shows, games)


def main():
    parser = argparse.ArgumentParser(description='生成 dist/index.html')
    parser.add_argument('--date', help='临时覆盖大会日期，例如 2027-09-20')
    parser.add_argument('--open', action='store_true', dest='do_open', help='构建完成后自动打开')
    args = parser.parse_args()

    for path in (TPL, CSS, FONT, LOGO):
        if not os.path.isfile(path):
            return fail('缺少文件：%s' % rel(path))

    cfg = load_content()
    validate(cfg)

    event = dict(cfg.get('event') or {})
    if args.date:
        event['date'] = args.date
    cfg['event'] = event

    vars_ = build_vars(event)
    missing = set()
    cfg = fill(cfg, vars_, missing)
    if missing:
        warn('这些占位符在 content/00-event.json 里找不到对应字段，已原样保留：%s'
             % '、'.join('{%s}' % k for k in sorted(missing)))

    html = read_text(TPL)

    # 0) 模板里静态兜底文案的占位符（首屏渲染前的默认文字）
    html = fill_text(html, vars_)

    # 1) 样式内联（字体转成 base64）
    if CSS_LINK not in html:
        return fail('template.html 里找不到样式引用：%s' % CSS_LINK)
    css = read_text(CSS).replace('__ZPIX_SRC__', data_uri(FONT, 'font/woff2'))
    if '__ZPIX_SRC__' in css:
        return fail('assets/style.css 里还有没替换的 __ZPIX_SRC__')
    html = html.replace(CSS_LINK, '<style>\n%s</style>' % css)

    # 2) 内容配置内联
    if not CFG_TAG.search(html):
        return fail('template.html 里找不到 <script id="cfg"> 占位')
    js = json.dumps(cfg, ensure_ascii=False, indent=2).replace('</', '<\\/')
    html = CFG_TAG.sub(lambda _m: '<script id="cfg">\nwindow.__CFG__ = %s;\n</script>' % js, html, count=1)

    # 3) 会徽内联
    if '__LOGO_SRC__' not in html:
        return fail('template.html 里找不到占位符 __LOGO_SRC__')
    html = html.replace('__LOGO_SRC__', data_uri(LOGO, 'image/png'))

    # 4) 静态标题跟着内容走（浏览器标签页 / 分享卡片）
    if TITLE_TAG.search(html) and cfg.get('meta', {}).get('htmlTitle'):
        html = TITLE_TAG.sub(lambda _m: '<title>%s</title>' % cfg['meta']['htmlTitle'], html, count=1)

    os.makedirs(DIST, exist_ok=True)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(html)

    print('[√] %s' % rel(OUT))
    print('    大会日期 %s %s · %s' % (vars_['dateIso'], vars_['weekday'], vars_.get('venue', '')))
    print('    %s' % stats(cfg))
    print('    体积 %.0f KB（字体与会徽已内联，可单独拷走）' % (len(html.encode('utf-8')) / 1024))

    if args.do_open:
        import webbrowser
        webbrowser.open('file:///' + OUT.replace('\\', '/'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
