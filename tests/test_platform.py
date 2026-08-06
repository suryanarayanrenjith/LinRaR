"""The machines and distributions LinRAR runs on, and the desktops it wires into.

Three lists have to agree with one another and none of them can be checked by
running the program on the machine in question, so they are checked against
each other instead:

  * ``install.sh`` maps a distribution to a package manager, and
    ``core/packages.py`` maps the same distributions for the Dependencies
    window: a name in one and not the other means the installer and the
    application would disagree about how software gets onto the machine;
  * every package manager either script names must know how to install with;
  * the architecture tables, which decide whether LinRAR offers something it
    cannot deliver: ``rar`` on POWER, an AppImage on RISC-V.

The file-manager integrations are checked as text: whether they are *written*
is proved by running the installer, which ``test_config.py`` and CI do.
"""
import os, re, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from linrar.core import packages, sfx
from linrar.core import platform as platform_check

PASS = FAIL = 0
def check(name, cond, extra=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  ok  {name}")
    else: FAIL += 1; print(f"FAIL  {name}  {extra}")

INSTALL = open(os.path.join(ROOT, "install.sh")).read()
UNINSTALL = open(os.path.join(ROOT, "uninstall.sh")).read()

print("== the architecture this is running on")
arch = platform_check.architecture()
check("it has a name", bool(arch.key), arch)
check("and a label", bool(arch.label))
check("machine() agrees with uname -m",
      platform_check.machine() == (os.uname().machine or "").lower())

print("\n== normalising what uname calls things")
for spelling, expected in (
    ("amd64", "x86_64"), ("x86_64", "x86_64"), ("X86_64", "x86_64"),
    ("arm64", "aarch64"), ("aarch64", "aarch64"),
    ("armv7l", "armv7l"), ("armhf", "armv7l"),
    ("i386", "i686"), ("i686", "i686"),
    ("riscv64", "riscv64"), ("ppc64le", "ppc64le"), ("s390x", "s390x"),
    ("loong64", "loongarch64"),
):
    check(f"{spelling} is {expected}",
          platform_check.normalise_machine(spelling) == expected,
          platform_check.normalise_machine(spelling))
check("an unknown machine is left as it is",
      platform_check.normalise_machine("babbage") == "babbage")
check("and still produces a usable answer",
      platform_check.architecture("babbage").key == "babbage")
check("which is honest about having no binaries",
      not platform_check.architecture("babbage").rarlab
      and not platform_check.architecture("babbage").appimage)

print("\n== what exists for which machine")
for key, (label, rarlab, appimage, bits) in platform_check.ARCHITECTURES.items():
    check(f"{key} is described", bool(label) and bits in (32, 64),
          (label, bits))
check("RARLAB's four are the ones marked",
      {k for k, v in platform_check.ARCHITECTURES.items() if v[1]}
      == {"x86_64", "i686", "aarch64", "armv7l"},
      {k for k, v in platform_check.ARCHITECTURES.items() if v[1]})
check("POWER, RISC-V, s390x and LoongArch have no rar",
      not any(platform_check.architecture(m).rarlab
              for m in ("ppc64le", "riscv64", "s390x", "loongarch64")))
check("and no AppImage runtime either",
      not any(platform_check.architecture(m).appimage
              for m in ("ppc64le", "riscv64", "s390x", "loongarch64")))

print("\n== the AppImage runtime")
check("every runtime architecture is one LinRAR knows",
      all(name in ("x86_64", "i686", "aarch64", "armhf")
          for name in sfx.RUNTIME_ARCHES))
check("this machine's runtime name is worked out",
      bool(sfx.runtime_arch()))
check("armv7l is called armhf, as AppImage calls it",
      sfx._APPIMAGE_NAMES["armv7l"] == "armhf")
real_machine = platform_check.machine
try:
    platform_check.machine = lambda: "riscv64"
    check("a machine with no runtime says so", not sfx.runtime_available())
    message = sfx.runtime_unavailable_message()
    check("and explains why", "RISC-V" in message, message[:80])
    check("and offers the alternative that does work",
          ".sfx" in message or "sfx stub" in message, message)
    platform_check.machine = lambda: "aarch64"
    check("a machine that has one says so", sfx.runtime_available())
    check("under AppImage's own name", sfx.runtime_arch() == "aarch64")
finally:
    platform_check.machine = real_machine
check("the two agree for every architecture LinRAR lists",
      all(platform_check.architecture(key).appimage
          == (sfx._APPIMAGE_NAMES.get(key, key) in sfx.RUNTIME_ARCHES)
          for key in platform_check.ARCHITECTURES))

print("\n== rar, which does not exist everywhere")
rar = next(d for d in packages.DEPENDENCIES if d.key == "rar")
check("rar is marked as a published binary", rar.binary_only)
check("nothing else is",
      not any(d.binary_only for d in packages.DEPENDENCIES if d.key != "rar"))
check("unrar is not, because it is built from source everywhere",
      not next(d for d in packages.DEPENDENCIES if d.key == "unrar").binary_only)
try:
    platform_check.machine = lambda: "ppc64le"
    check("on POWER, rar is not available", not rar.available_here())
    reason = rar.unavailable_reason()
    check("and the reason names this machine", "POWER" in reason, reason)
    check("and says what still works", "without it" in reason, reason)
    check("while unrar still is",
          next(d for d in packages.DEPENDENCIES
               if d.key == "unrar").available_here())
    platform_check.machine = lambda: "x86_64"
    check("on x86-64 it is available", rar.available_here())
    check("with nothing to explain", rar.unavailable_reason() == "")
finally:
    platform_check.machine = real_machine

print("\n== install.sh knows about the same machines")
for machine in ("x86_64", "aarch64", "riscv64", "ppc64le", "s390x",
                "loongarch64", "armv7l"):
    check(f"install.sh handles {machine}", machine in INSTALL)
check("it reports the architecture", "architecture:" in INSTALL)
check("it warns where rar has no build", "does not publish 'rar'" in INSTALL)
check("and records it in the receipt", "printf 'arch=%s\\n'" in INSTALL)

print("\n== distributions")
# Every ID named in install.sh's case statement, pulled back out of it.
block = INSTALL[INSTALL.index("for candidate in \"${DISTRO_ID}\""):
                INSTALL.index("[ -n \"$PM\" ] && break")]
# A case pattern is written across several lines, each continued with a
# backslash, so the continuations are joined before anything is matched --
# counting only the last line of each would report a third of the real number.
joined = re.sub(r"\\\n\s*", "", block)
shell_ids = set()
for line in joined.splitlines():
    match = re.match(r"^\s*([a-z0-9_*|-]+)\)\s+PM=", line)
    if not match:
        continue
    for token in match.group(1).split("|"):
        token = token.strip()
        if token and "*" not in token:
            shell_ids.add(token)
print(f"       ({len(shell_ids)} distributions in install.sh, "
      f"{len(packages._DISTRO_MANAGERS)} in packages.py, "
      f"{len(packages.MANAGERS)} package managers)")
check("install.sh names a great many distributions", len(shell_ids) > 90,
      len(shell_ids))
check("packages.py names a great many too",
      len(packages._DISTRO_MANAGERS) > 90, len(packages._DISTRO_MANAGERS))
# The two lists do not have to be identical -- install.sh knows about
# derivatives whose packages are their parent's -- but a family in one and
# missing entirely from the other is a mistake.
for family in ("debian", "fedora", "arch", "alpine", "gentoo", "void",
               "altlinux", "guix", "crux"):
    check(f"both lists know {family}",
          family in shell_ids and family in packages._DISTRO_MANAGERS)

managers_in_shell = set(re.findall(r'PM="([a-z0-9-]+)"', INSTALL))
check("every manager install.sh chooses, it can also install with",
      all(f"        {name})" in INSTALL or f"        {name})" in INSTALL
          or re.search(rf"^\s+{re.escape(name)}\)", INSTALL, re.M)
          for name in managers_in_shell),
      managers_in_shell)

for name in sorted(managers_in_shell):
    if name == "nix":
        continue          # declarative: install.sh deliberately refuses
    check(f"install.sh has package names for {name}",
          f"{name}:archive)" in INSTALL, name)

known = set(packages.MANAGERS)
check("every manager the Dependencies window offers has a command",
      all(m.install and m.remove for m in packages.MANAGERS.values()))
check("every distribution maps to a manager that exists",
      set(packages._DISTRO_MANAGERS.values()) <= known,
      set(packages._DISTRO_MANAGERS.values()) - known)
check("every package name is filed under a manager that exists",
      all(set(d.packages) <= known for d in packages.DEPENDENCIES),
      [sorted(set(d.packages) - known) for d in packages.DEPENDENCIES])
check("the essential tools can be installed on every manager but the odd one",
      sum(1 for m in known
          if next(d for d in packages.DEPENDENCIES
                  if d.key == "unrar").packages_for(packages.MANAGERS[m]))
      >= len(known) - 4,
      known)

print("\n== the big families are all covered")
for distro, manager in (
    ("debian", "apt"), ("ubuntu", "apt"), ("fedora", "dnf"),
    ("rhel", "dnf"), ("arch", "pacman"), ("opensuse", "zypper"),
    ("alpine", "apk"), ("void", "xbps"), ("gentoo", "emerge"),
    ("solus", "eopkg"), ("altlinux", "apt-rpm"), ("guix", "guix"),
    ("slackware", "slackpkg"), ("crux", "prt-get"), ("nutyx", "cards"),
    ("slitaz", "tazpkg"), ("openwrt", "opkg"), ("clear-linux-os", "swupd"),
):
    check(f"{distro} -> {manager}",
          packages._DISTRO_MANAGERS.get(distro) == manager,
          packages._DISTRO_MANAGERS.get(distro))

print("\n== file managers")
for manager, needle in (
    ("Dolphin / Konqueror", "kio/servicemenus"),
    ("Nemo", "nemo/actions"),
    ("Nautilus", "nautilus/scripts"),
    ("Caja", "caja/scripts"),
    ("Thunar", "Thunar/uca.xml"),
    ("PCManFM / LXQt / SpaceFM", "file-manager/actions"),
    ("Pantheon Files", "contractor"),
    ("Deepin", "oem-menuextensions"),
    ("Krusader", "krusader/useractions.xml"),
):
    check(f"install.sh wires up {manager}", needle in INSTALL, needle)
check("the DES-EMA files declare themselves as actions", "Type=Action" in INSTALL)
check("and are gathered into one submenu", "Type=Menu" in INSTALL)
check("Deepin gets its suffix list", "X-DFM-SupportSuffix" in INSTALL)
check("Krusader gets a category", "KrusaderUserActions" in INSTALL)
check("the suffix list is built once and reused",
      INSTALL.count("ARCHIVE_SUFFIXES=") == 1)
check("and covers well past the original ten",
      len(re.search(r'ARCHIVE_SUFFIXES="([^"]+)"', INSTALL, re.S)
          .group(1).split()) > 40)

print("\n== what LinRAR takes over, and what it only offers")
check("there are two MIME lists", "MIMES_SECONDARY=" in INSTALL)
check("the default-handler loop uses the narrow one",
      'read -r -a MIME_LIST <<< "$MIMES"' in INSTALL)
check("the desktop entry offers the wide one", "MimeType=${MIMES_ALL}" in INSTALL)
secondary = re.search(r'MIMES_SECONDARY="(.*?)"\n', INSTALL, re.S).group(1)
primary = re.search(r'\nMIMES="(.*?)"\n\n', INSTALL, re.S).group(1)
for mime in ("application/java-archive",
             "application/vnd.android.package-archive",
             "application/epub+zip",
             "application/vnd.debian.binary-package"):
    check(f"LinRAR does not claim {mime.split('/')[-1]}",
          mime in secondary and mime not in primary, mime)
for mime in ("application/x-rar", "application/zip",
             "application/x-7z-compressed"):
    check(f"but it does claim {mime.split('/')[-1]}", mime in primary)
check("no document format is claimed as a default",
      "officedocument" not in primary and "opendocument" not in primary)

print("\n== uninstall reverses the new entries too")
check("it works from the manifest", ".install-manifest" in UNINSTALL)
check("which is what records every file written",
      INSTALL.count("record ") >= 3)

print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
