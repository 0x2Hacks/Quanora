from pathlib import Path
from rich.console import Console
from rich.text import Text
from rich.style import Style
import colorsys


def print_rainbow_logo():
    """
    Reads the logo file and prints it to the console with a rainbow gradient effect.
    """
    path = Path(__file__).parent / "assets" / "logo.txt"
    try:
        if not path.exists():
            print(f"[Warning] Logo file not found at: {path}")
            return

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        
        if not lines:
            return

        console = Console()
        total_lines = len(lines)
        
        print()
        for i, line in enumerate(lines):
            hue = i / total_lines
            r, g, b = colorsys.hls_to_rgb(hue, 0.6, 1.0)
            color_hex = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
            text = Text(line, style=Style(color=color_hex, bold=True))
            console.print(text)
        print()

    except Exception as e:
        print(f"[Error] Failed to display logo: {e}")

if __name__ == "__main__":
    print_rainbow_logo()
