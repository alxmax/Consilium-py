"""Every subprocess call to git, in one place."""
import os, re, subprocess



def _git(args, cwd=None, timeout=10):  # implements: ARCH-GITRUN-067  # implements: REQ-GITRUN-993
    """Run one git command; return its stdout, or None when git could not answer.

    Every git call in this engine is advisory or fail-open — a missing git, a directory
    that is not a work tree, a non-zero exit all mean "unknown", never "raise". Eleven
    call sites each decided that for themselves and disagreed on the details that matter:

    - `encoding="utf-8"` is not cosmetic. With `text=True` alone Python decodes with the
      LOCALE codec, so on a Windows console (cp1252) a non-ASCII path or remote URL either
      mojibakes or raises inside a bare `except`, and the caller reads the empty result as
      "nothing found" — a check failing OPEN, silently, on one platform. Three sites had
      the encoding because someone was bitten; the other eight did not.
    - Two of them used `check_output(...).decode()`, which is the same bug with no `text=`.
    - The exception nets ranged from `Exception` to `(OSError, SubprocessError)`, so a
      `UnicodeDecodeError` was caught by some and fatal in others.

    Decoding stays strict on purpose: a path git could not hand over as UTF-8 must surface
    as None (fall back to the full, safe answer), never as a replacement character that
    silently fails to match a real file.
    """
    try:
        r = subprocess.run(["git"] + list(args), cwd=cwd or None,
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except Exception:
        return None
    return r.stdout if r.returncode == 0 else None


def _git_root(root):  # implements: ARCH-GITRUN-067  # implements: REQ-GITRUN-993
    """The work-tree root containing `root`, or `root` itself when git cannot say.

    Three call sites resolved the toplevel with three spellings, which is one more than
    a repo entered from a sub-directory can afford: the site page and the scan root have
    to agree on where the project starts."""
    return (_git(["-C", root, "rev-parse", "--show-toplevel"], timeout=3) or "").strip() or root


def _git_remote_url(root):  # implements: ARCH-GITRUN-067  # implements: REQ-GITRUN-993
    """`remote.origin.url`, or "" when git is absent / there is no remote."""
    return (_git(["-C", root, "config", "--get", "remote.origin.url"], timeout=3) or "").strip()


def _repo_name(root):  # implements: ARCH-MAP-007  # implements: REQ-MAP-871
    """Best-effort `owner/repo` (else the repo directory name) identifying the
    project this map describes, for display in the viewer header. Tries the git
    `remote.origin.url`, then the directory name; returns None when nothing
    resolves. Never raises and never blocks map generation — git may be absent or
    the tree may not be a checkout. Environment-derived (it differs across forks
    and clones), so it is excluded from the `map --check` freshness diff (see
    `_strip_generated`).

    `REQMAP_REPO` env var overrides the derived value: set it to a public-facing
    slug (e.g. on a private dev repo that publishes elsewhere, so the inlined
    `repo` never leaks the dev remote), or to "" to emit no repo at all."""
    override = os.environ.get("REQMAP_REPO")
    if override is not None:
        return override or None
    url = _git_remote_url(root)
    if url:
        slug = url[:-4] if url.endswith(".git") else url
        parts = [p for p in re.split(r"[:/]", slug.rstrip("/")) if p]
        if len(parts) >= 2:
            return "/".join(parts[-2:])
    return os.path.basename(os.path.abspath(root)) or None


def _normalise_remote(url):  # implements: ARCH-SITE-026
    """Normalise a git remote URL to a https web URL (https://host/owner/repo),
    or None when empty/unparseable. Handles scp-style (git@host:owner/repo.git),
    ssh:// and https:// forms; strips a trailing `.git`. Pure string work."""
    url = (url or "").strip()
    if not url:
        return None
    if url.endswith(".git"):
        url = url[:-4]
    m = re.match(r"^[\w.+-]+@([\w.-]+):(.+)$", url)          # scp-style
    if m:
        return "https://{}/{}".format(m.group(1), m.group(2))
    # optional :port (corporate / self-hosted ssh remotes) is dropped, keeping
    # group(1)=host and group(2)=path so the web URL stays clickable
    m = re.match(r"^(?:ssh|git|https?)://(?:[^@/]+@)?([\w.-]+)(?::\d+)?/(.+)$", url)
    if m:
        return "https://{}/{}".format(m.group(1), m.group(2))
    return url if "://" in url else None


def _git_remote_web_url(root):  # implements: ARCH-SITE-026
    """The project's web URL from git `remote.origin.url`, or None when git is
    absent / no remote / not a checkout. Honours the REQMAP_REPO override (a
    bare slug becomes https://github.com/<slug>; empty disables). Never raises."""
    override = os.environ.get("REQMAP_REPO")
    if override is not None:
        if not override:
            return None
        return override if "://" in override else "https://github.com/" + override
    url = _git_remote_url(root)
    return _normalise_remote(url)


def _git_dirty(root):  # implements: REQ-RETIRE-961
    """True when the working tree has uncommitted changes. Fails OPEN (False) when
    git is absent or this is not a repository: a missing safety net must not block a
    legitimate operation, and the plan was printed before this point either way."""
    return bool((_git(["status", "--porcelain"], cwd=root or ".", timeout=20) or "").strip())


def _git_branch(root):  # implements: ARCH-GITRUN-067  # implements: REQ-PLANBRANCH-1011
    """The checked-out branch name, or None when git cannot say.

    Fail-open like every git call here: a detached HEAD answers "HEAD", which is not a
    branch, and a tarball with no work tree answers nothing. Both read as unknown, and
    the caller shows what it showed before."""
    out = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    name = (out or "").strip()
    return name or None if name and name != "HEAD" else None
