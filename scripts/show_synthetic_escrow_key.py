"""Operator-local GUI ONLY; never reads a Bitwarden vault or writes clipboard."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session-root', required=True)
    args = parser.parse_args(argv)
    window = None
    try:
        from src.recovery.s3_manual_drill import read_for_display
        import tkinter as tk
        from tkinter import messagebox
        material = read_for_display(args.session_root)
        window = tk.Tk()
        window.title('Football Platform - SYNTHETIC KEY ONLY')
        window.resizable(False, False)
        tk.Label(window, text='TEST ONLY - not an S3 backup key', padx=24, pady=12).pack()
        tk.Label(window, text='Session: ' + material.session_id, padx=24).pack()
        tk.Label(window, text='Manually type these 4 lines into key_hex in Bitwarden.\n'
                 'Join them into 64 hex characters. No clipboard, screenshots or chat.',
                 padx=24, pady=12).pack()
        # A Label is not a selectable/copyable text entry; no copy button or bindings.
        grouped = '\n'.join(material.hex_key[n:n + 16] for n in range(0, 64, 16))
        tk.Label(window, text=grouped, font=('Consolas', 16), padx=24, pady=12).pack()
        tk.Button(window, text='Close', command=window.destroy, padx=20, pady=6).pack(pady=12)

        def failed_callback(*_):
            messagebox.showerror('Synthetic viewer', 'Viewer failed. Close and notify the operator.')
            window.destroy()
        window.report_callback_exception = failed_callback
        window.mainloop()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        # Never interpolate key bytes, Tk error messages or arbitrary exception text.
        print('SYNTHETIC_KEY_VIEW_FAILED', file=sys.stderr)
        return 1
    finally:
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
