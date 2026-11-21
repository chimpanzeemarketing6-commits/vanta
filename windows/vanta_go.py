"""Entry point for VantaGo.exe: Vanta's Legion Go edition (Legion buttons, TDP, fans, charge limit, lights, presets)."""
import os

os.environ["VANTA_EDITION"] = "go"

import vanta  # noqa: E402

if __name__ == "__main__":
    vanta.main()
