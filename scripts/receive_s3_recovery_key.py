"""Manual production-key comparison. No Bitwarden integration or S3 operation."""
import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def input_status(text):
    """Local length/format feedback only; never return characters or fingerprints."""
    if re.fullmatch(r'[0-9a-fA-F]*', text) is None:
        return f'{len(text)}/64 characters - non-hex characters or spaces; use English keyboard layout.'
    return f'{len(text)}/64 hex characters' + (' - format OK (not yet compared)' if len(text) == 64 else '')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--key-id', required=True, help='non-secret reference, NEVER key material')
    parser.add_argument('--confirm-saved-and-viewer-closed', action='store_true')
    args = parser.parse_args(argv)
    window = None
    value = None
    try:
        from src.recovery.runtime import RecoveryError
        from src.recovery.s3_key_escrow import NOTE, begin_recovery, confirm_recovered
        import tkinter as tk
        from tkinter import messagebox
        context = begin_recovery(args.key_id, saved_and_viewer_closed=args.confirm_saved_and_viewer_closed)
        window = tk.Tk()
        window.title('Football Platform - PRODUCTION KEY VERIFICATION')
        window.resizable(False, False)
        tk.Label(window, text='Enter key_hex from the production note, NOT the old Recovery Test note.', padx=24, pady=12).pack()
        tk.Label(window, text='Note: ' + NOTE + '\nKey ID: ' + context.key_id, padx=24).pack()
        tk.Label(window, text='Original key is retained and used only for comparison.\n'
                 'Enter exactly 64 hex characters. Manual paste is allowed; no chat or screenshots.\n'
                 'Clipboard history/sync may retain the key. Choose the real source below.\n'
                 'Never enter a Bitwarden password, MFA or account recovery code.', padx=24, pady=12).pack()
        value = tk.StringVar(window)
        entry = tk.Entry(window, textvariable=value, show='*', width=70, font=('Consolas', 12))
        entry.pack(padx=24, pady=8)
        # Native user-initiated copy/paste only: no automatic clipboard API calls.
        visible = tk.BooleanVar(window, value=False)

        def toggle_visibility():
            entry.configure(show='' if visible.get() else '*')
        tk.Checkbutton(window, text='Show entered key (private screen only)', variable=visible,
                       command=toggle_visibility).pack(pady=4)
        status = tk.StringVar(window, value=input_status(''))
        value.trace_add('write', lambda *_: status.set(input_status(value.get())))
        tk.Label(window, textvariable=status, padx=24).pack(pady=4)
        source = tk.StringVar(window, value='')
        tk.Radiobutton(window, text='From the PHONE / independently retrieved (operator attestation)',
                       variable=source, value='phone').pack(pady=4)
        tk.Radiobutton(window, text='From DESKTOP note (diagnostic match only, not independent recovery)',
                       variable=source, value='desktop').pack(pady=4)

        def submit():
            try:
                result = confirm_recovered(context, value.get(), phone_attested=source.get() == 'phone',
                                           desktop_attested=source.get() == 'desktop')
            except Exception as exc:
                messages = {'S3_ESCROW_PHONE_ATTESTATION_REQUIRED': 'Choose the actual input source: phone or desktop.',
                            'S3_ESCROW_KEY_HEX_INVALID': 'Enter exactly 64 hex characters, without spaces.',
                            'S3_ESCROW_KEY_MISMATCH': 'Key mismatch. Recheck the selected note/source. No receipt saved.',
                            'S3_ESCROW_ORIGINAL_CHANGED': 'Original key changed. Stop and notify the operator.',
                            'S3_ESCROW_RECOVERY_ALREADY_RECORDED': 'Already verified. Close; do not repeat.'}
                code = str(exc) if isinstance(exc, RecoveryError) else ''
                messagebox.showerror('Production key verification', messages.get(code, 'Verification failed. Stop and notify the operator.'))
                return
            value.set('')
            visible.set(False)
            entry.configure(show='*')
            route = ('Phone route attested.' if result['independent_route_verified']
                     else 'DESKTOP DIAGNOSTIC ONLY. Independent recovery is still BLOCKED.')
            messagebox.showinfo('Production key verification', 'MATCH - fingerprints equivalent.\n'
                                'Original retained; no recovered-key copy saved.\n'
                                + route + '\n'
                                'Return to chat. No S3 backup was started.')
            window.destroy()

        tk.Button(window, text='Compare in memory', command=submit, padx=20, pady=8).pack(pady=12)

        def callback_failed(*_):
            messagebox.showerror('Production key verification', 'Input failed. Close and notify the operator.')
            window.destroy()
        window.report_callback_exception = callback_failed
        entry.focus_set()
        window.mainloop()
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception:
        print('S3_PRODUCTION_KEY_RECOVERY_FAILED', file=sys.stderr)
        return 1
    finally:
        if value is not None:
            try:
                value.set('')
            except Exception:
                pass
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass


if __name__ == '__main__':
    sys.exit(main())
