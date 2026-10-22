"""Operator-local production-key viewer. No Bitwarden, clipboard or backup access."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-id', required=True, help='non-secret identifier only, NEVER key material')
    parser.add_argument('--confirm-local-display', action='store_true')
    args = parser.parse_args(argv)
    window = None
    try:
        from src.recovery.s3_key_escrow import NOTE, read_for_display
        import tkinter as tk
        from tkinter import messagebox
        material = read_for_display(args.key_id, confirmed=args.confirm_local_display)
        window = tk.Tk()
        window.title('Football Platform - PRODUCTION RECOVERY KEY')
        window.resizable(False, False)
        tk.Label(window, text='PRODUCTION KEY - private display, not a backup launch', padx=24, pady=12).pack()
        tk.Label(window, text='Bitwarden secure note: ' + NOTE, padx=24).pack()
        tk.Label(window, text='Key ID: ' + material.key_id, padx=24).pack()
        tk.Label(window, text='Created UTC: ' + material.created_at + '\n'
                 'purpose=production-s3-backup | encoding=hex\n'
                 'backup_session=PENDING_NOT_CREATED', padx=24, pady=8).pack()
        tk.Label(window, text='Type these 4 lines as ONE 64-character key_hex value.\n'
                 'No clipboard, screenshots, shell history, chat or plaintext export.\n'
                 'Check every digit on the phone, then close this window.\n'
                 'Do not delete the original key. Live backup remains BLOCKED.', padx=24, pady=12).pack()
        grouped = '\n'.join(material.hex_key[n:n + 16] for n in range(0, 64, 16))
        tk.Label(window, text=grouped, font=('Consolas', 16), padx=24, pady=12).pack()
        tk.Button(window, text='Close (does NOT confirm escrow)', command=window.destroy, padx=20, pady=6).pack(pady=12)

        def failed_callback(*_):
            messagebox.showerror('Production key viewer', 'Viewer failed. Stop and notify the operator.')
            window.destroy()
        window.report_callback_exception = failed_callback
        window.mainloop()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        print('S3_PRODUCTION_KEY_VIEW_FAILED', file=sys.stderr)
        return 1
    finally:
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
