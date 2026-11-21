"""Entry point for Vanta-Preview.exe: no admin prompt, separate settings, and it won't change the PC unless you allow it."""
import os

os.environ["VANTA_PREVIEW"] = "1"

import vanta  # noqa: E402

if __name__ == "__main__":
    vanta.main()
