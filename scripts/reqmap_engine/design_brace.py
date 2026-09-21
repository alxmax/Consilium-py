"""`ask --design`, brace-language side: masking and heuristics for JS/TS/Java/C-family sources.
"""
import re

from .design import _design_chain_findings, _design_shape_findings, _design_standards


# ---- brace languages, through masked text
_BRACE_KEYWORDS = frozenset(("if", "for", "while", "switch", "catch", "else", "return", "do", "try",
                             "sizeof", "typeof", "new", "throw", "await", "yield", "defer", "match",
                             "elif", "unless", "until", "foreach", "using", "lock", "synchronized"))
_BRACE_FUNC_RE = re.compile(
    r"(?<![\w.])(?:(?:async|static|public|private|protected|export|default|override|virtual|inline|"
    r"constexpr|extern|final|abstract|unsafe|pub(?:\([^)]*\))?|func|fn|fun|function|def)\s+)*"
    r"(?:[A-Za-z_][\w:<>\[\],*&?]*\s+[*&]*)?([A-Za-z_]\w*)\s*(?:<[^>()]*>)?\s*"
    r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)"
    r"\s*(?:->\s*[\w:<>\[\],*&?.]+|:\s*[\w:<>\[\],*&?.|]+|"
    r"const|override|noexcept|throws\s+[\w, ]+)?\s*\{")
_BRACE_ARROW_RE = re.compile(
    r"(?<![\w.])(?:const|let|var|val)\s+([A-Za-z_]\w*)\s*(?::[^=]+)?=\s*"
    r"(?:async\s*)?\(([^()]*)\)\s*(?::\s*[^=]+)?=>\s*\{")
_BRACE_CLASS_RE = re.compile(
    r"(?<![\w.])(?:class|struct|interface)\s+([A-Za-z_]\w*)(?:\s*<[^>{]*>)?\s*"
    r"([^{;]*)\{")
_BRACE_IF_RE = re.compile(r"(?<![\w.])(else\s+)?if\s*\(")
_BRACE_SWITCH_RE = re.compile(r"(?<![\w.])switch\s*\(\s*([A-Za-z_][\w.]*)\s*\)\s*\{")
_BRACE_CASE_RE = re.compile(r"(?<![\w.])case\s+[^:]{1,60}:")
_BRACE_TYPE_TEST_RE = re.compile(
    r"(?:([A-Za-z_]\w*)\s+instanceof\b|typeof\s+([A-Za-z_]\w*)\s*[!=]==?|"
    r"dynamic_cast\s*<[^>]*>\s*\(\s*([A-Za-z_]\w*)|"
    r"([A-Za-z_]\w*)\s+is\s+[A-Z]\w*)")
_BRACE_EQ_TEST_RE = re.compile(
    r"(?<![\w.])([A-Za-z_][\w.]*)\s*[!=]==?\s*(?:\d+|[A-Z_][A-Z0-9_]{2,}|\w+::\w+)")


def _mask_quote_end(src, q, j, n):
    """Index of the closing quote `q` (or a terminating bare newline) scanning
    forward from j, matching the same escape/newline rules as `_design_mask`."""
    while j < n and src[j] != q:
        j += 2 if src[j] == "\\" else 1
        if j < n and src[j] == "\n" and q != "`":
            break
    return j


def _design_mask(src):
    """The source with comments and string/char literals replaced by spaces (newlines
    kept), so brace matching and keyword searches never see text."""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        two = src[i:i + 2]
        if two == "//":
            j = src.find("\n", i)
            j = n if j == -1 else j
            out.append(" " * (j - i)); i = j
        elif two == "/*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:j])); i = j
        elif c in "\"'`":
            q, j = c, i + 1
            j = _mask_quote_end(src, q, j, n)
            j = min(j + 1, n)
            out.append("".join("\n" if ch == "\n" else " " for ch in src[i:j])); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


def _design_block_end(masked, open_idx):
    """Index just past the `}` matching the `{` at open_idx (or len(masked))."""
    depth, i, n = 0, open_idx, len(masked)
    while i < n:
        if masked[i] == "{":
            depth += 1
        elif masked[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _design_param_names(params):
    names = []
    for p in params.split(","):
        p = p.strip()
        if not p or p in ("...", "void"):
            continue
        p = p.split("=", 1)[0]
        if ":" in p:                      # TS / Kotlin / Swift: name: Type
            p = p.split(":", 1)[0]
        toks = re.findall(r"[A-Za-z_]\w*", p)
        if toks:
            names.append(toks[-1] if ":" not in p else toks[0])
    return names


def _paren_match_end(masked, paren):
    # implements: REQ-DESIGN-955
    """Index of the ')' matching the '(' at paren (or len(masked) if unmatched)."""
    depth, i = 0, paren
    while i < len(masked):
        if masked[i] == "(":
            depth += 1
        elif masked[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    return i


def _design_brace(rel, src):  # implements: REQ-DESIGN-955
    masked = _design_mask(src)
    out, fns, classes = [], [], []
    n_top = 0

    def depth_at(idx):
        return masked.count("{", 0, idx) - masked.count("}", 0, idx)

    def add_fn(name, params, brace_idx, line):
        end = _design_block_end(masked, brace_idx)
        body = masked[brace_idx:end]
        depth, best = 0, 0
        for ch in body:
            if ch == "{":
                depth += 1; best = max(best, depth)
            elif ch == "}":
                depth -= 1
        fns.append({"name": name, "line": line, "n_lines": body.count("\n") + 1,
                    "depth": max(best - 1, 0), "params": _design_param_names(params),
                    "top": depth_at(brace_idx) == 0, "end": end})
    for m in _BRACE_FUNC_RE.finditer(masked):
        if m.group(1) in _BRACE_KEYWORDS:
            continue
        add_fn(m.group(1), m.group(2), m.end() - 1, masked.count("\n", 0, m.start()) + 1)
    for m in _BRACE_ARROW_RE.finditer(masked):
        add_fn(m.group(1), m.group(2), m.end() - 1, masked.count("\n", 0, m.start()) + 1)
    fns.sort(key=lambda f: f["line"])
    n_top = sum(1 for f in fns if f["top"])
    for m in _BRACE_CLASS_RE.finditer(masked):
        start, end = m.end() - 1, _design_block_end(masked, m.end() - 1)
        cleaned = re.sub(
            r"\b(?:extends|implements|public|private|protected|virtual|final|with)\b", " ",
            m.group(2))
        bases = set(re.findall(r"[A-Za-z_]\w*", cleaned))
        methods = {}
        for f in fns:
            if start < f["end"] <= end and f["name"] not in _BRACE_KEYWORDS:
                fstart = masked.rfind(f["name"], start, f["end"])
                methods[f["name"]] = re.sub(r"\s+", " ", src[fstart:f["end"]]).strip()
        classes.append({"name": m.group(1), "line": masked.count("\n", 0, m.start()) + 1,
                        "bases": bases, "methods": methods})
        if depth_at(start) == 0:
            n_top += 1
    out += _design_shape_findings(rel, fns, classes)
    chains, cur = [], None
    for m in _BRACE_IF_RE.finditer(masked):
        paren = m.end() - 1
        i = _paren_match_end(masked, paren)
        cond = masked[paren:i + 1]
        tests = [("type", next(g for g in t if g)) for t in _BRACE_TYPE_TEST_RE.findall(cond)]
        tests += [("eq", n) for n in _BRACE_EQ_TEST_RE.findall(cond)]
        if m.group(1) and cur is not None:
            cur[1].extend(tests)
        else:
            cur = (masked.count("\n", 0, m.start()) + 1, tests)
            chains.append(cur)
    for m in _BRACE_SWITCH_RE.finditer(masked):
        body = masked[m.end() - 1:_design_block_end(masked, m.end() - 1)]
        n_cases = len(_BRACE_CASE_RE.findall(body))
        chains.append((masked.count("\n", 0, m.start()) + 1, [("eq", m.group(1))] * n_cases))
    out += _design_chain_findings(rel, chains)
    return out + _design_standards(rel, src, n_top, [])
