import os
import sys

def generate_version_info():
    # Read version from root VERSION file
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    version_file = os.path.join(root_dir, 'VERSION')
    
    try:
        with open(version_file, 'r') as f:
            version_str = f.read().strip()
    except FileNotFoundError:
        print(f"Error: VERSION file not found at {version_file}")
        sys.exit(1)

    # Parse version (x.y.z) -> (x, y, z, 0)
    parts = version_str.split('.')
    while len(parts) < 4:
        parts.append('0')
    
    # Ensure all parts are integers
    try:
        ver_tuple = tuple(int(p) for p in parts[:4])
    except ValueError:
        print(f"Error: Invalid version format '{version_str}'. Must be numeric.")
        sys.exit(1)

    ver_tuple_str = str(ver_tuple)
    version_str_full = f"{version_str}.0" if len(parts) < 4 else version_str

    content = f"""# UTF-8
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
    # filevers and prodvers should be always a tuple with four items: (1, 2, 3, 4)
    # Set not needed items to zero 0.
    filevers={ver_tuple_str},
    prodvers={ver_tuple_str},
    # Contains a bitmask that specifies the valid bits 'flags'
    mask=0x3f,
    # Contains a bitmask that specifies the Boolean attributes of the file.
    flags=0x0,
    # The operating system for which this file was designed.
    # 0x4 - NT and there is no need to change it.
    OS=0x40004,
    # The general type of file.
    # 0x1 - the file is an application.
    fileType=0x1,
    # The function of the file.
    # 0x0 - the function is not defined for this fileType
    subtype=0x0,
    # Creation date and time stamp.
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'Valery Giner'),
            StringStruct(u'FileDescription', u'PGVectorRAGIndexer Desktop App Installer'),
            StringStruct(u'FileVersion', u'{version_str_full}'),
            StringStruct(u'InternalName', u'PGVectorRAGIndexer-Setup'),
            StringStruct(u'LegalCopyright', u'© 2024-2025 Valery Giner. All rights reserved.'),
            StringStruct(u'OriginalFilename', u'PGVectorRAGIndexer-Setup.exe'),
            StringStruct(u'ProductName', u'PGVectorRAGIndexer'),
            StringStruct(u'ProductVersion', u'{version_str_full}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""
    
    # Write to windows_installer/version_info.txt
    output_path = os.path.join(root_dir, 'windows_installer', 'version_info.txt')
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Successfully generated {output_path} with version {version_str}")

if __name__ == '__main__':
    generate_version_info()
