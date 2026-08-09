import os
import base64

# Resolves relative to this script's own location, not the current working
# directory -- so this works whether you run it from the project root
# (python dependencies\update-launcher-icon.py) or from inside dependencies/
# itself, since both the .ico and icon_data.py live alongside this script.
_here = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(_here, "att-unlocked-full.ico"), "rb") as f:
    data = base64.b64encode(f.read()).decode()

with open(os.path.join(_here, "icon_data.py"), "w") as f:
    f.write(f'ICON_B64 = "{data}"\n')

print("Done —", len(data), "chars written")
