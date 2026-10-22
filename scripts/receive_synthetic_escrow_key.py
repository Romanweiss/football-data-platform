"""Manual PHONE-to-local input for a synthetic key, never a Bitwarden integration."""
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
        from src.recovery.runtime import RecoveryError
        from src.recovery.s3_manual_drill import receive_from_phone, recovery_record
        import tkinter as tk
        from tkinter import messagebox
        root, record = recovery_record(args.session_root)
        if any((root / 'recovered').iterdir()):
            raise RecoveryError('SYNTHETIC_RECOVERED_KEY_EXISTS')
        window = tk.Tk()
        window.title('Football Platform - SYNTHETIC PHONE RECOVERY')
        window.resizable(False, False)
        tk.Label(window, text='TEST ONLY. Original local key has been removed.', padx=24, pady=12).pack()
        tk.Label(window, text='Session: ' + record['session_id'], padx=24).pack()
        tk.Label(window, text='Read key_hex FROM YOUR PHONE. Type exactly 64 hex characters.\n'
                 'No clipboard, screenshots, shell history or chat.\n'
                 'Do NOT enter a Bitwarden password, MFA code or account recovery code.', padx=24, pady=12).pack()
        value = tk.StringVar(window)
        entry = tk.Entry(window, textvariable=value, show='*', width=70)
        entry.pack(padx=24, pady=8)
        for event in ('<<Paste>>', '<<Copy>>', '<<Cut>>', '<Control-v>', '<Control-V>',
                      '<Control-c>', '<Control-C>', '<Control-x>', '<Control-X>', '<Shift-Insert>'):
            entry.bind(event, lambda _: 'break')
        phone = tk.BooleanVar(window, value=False)
        tk.Checkbutton(window, text='I read this key from the phone, not a local copy.', variable=phone).pack(pady=8)

        def submit():
            try:
                receive_from_phone(args.session_root, value.get(), phone_attested=phone.get())
            except Exception as exc:
                messages = {
                    'SYNTHETIC_PHONE_ATTESTATION_REQUIRED': 'Confirm the phone source checkbox.',
                    'SYNTHETIC_KEY_HEX_INVALID': 'Enter exactly 64 hex characters, without spaces.',
                    'S3_MANIFEST_AUTHENTICATION_FAILED': 'Key does not match. Recheck the PHONE. Nothing saved.',
                    'SYNTHETIC_RECOVERED_KEY_EXISTS': 'Already captured. Do not overwrite; return to chat.',
                }
                code = str(exc) if isinstance(exc, RecoveryError) else ''
                messagebox.showerror('Synthetic recovery', messages.get(code, 'Capture failed. Stop and notify the operator.'))
                return
            value.set('')
            messagebox.showinfo('Synthetic recovery', 'Synthetic key saved. Offline verify PASS.\n'
                                'Return to chat; restore and cleanup are still pending.')
            window.destroy()

        tk.Button(window, text='Verify and save synthetic key', command=submit, padx=20, pady=8).pack(pady=12)
        def callback_failed(*_):
            messagebox.showerror('Synthetic recovery', 'Input failed. Close and notify the operator.')
            window.destroy()
        window.report_callback_exception = callback_failed
        entry.focus_set()
        window.mainloop()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        print('SYNTHETIC_PHONE_INPUT_FAILED', file=sys.stderr)
        return 1
    finally:
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
