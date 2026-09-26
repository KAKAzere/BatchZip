import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.version import APP_VERSION, windows_version


def render_version_info(version):
    numeric_version = windows_version(version)

    return f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric_version},
    prodvers={numeric_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        u'040904B0',
        [
          StringStruct(u'CompanyName', u'KAKAzere'),
          StringStruct(u'FileDescription', u'BatchZip Windows Batch Compression Tool'),
          StringStruct(u'FileVersion', u'{version}'),
          StringStruct(u'InternalName', u'BatchZip'),
          StringStruct(u'LegalCopyright', u'Copyright (c) 2026 KAKAzere'),
          StringStruct(u'OriginalFilename', u'BatchZip.exe'),
          StringStruct(u'ProductName', u'BatchZip'),
          StringStruct(u'ProductVersion', u'{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""


def generate_version_info(output_path=None):
    output = output_path or PROJECT_ROOT / "version_info.txt"
    resource = render_version_info(APP_VERSION)
    output.write_text(resource, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    generate_version_info()
