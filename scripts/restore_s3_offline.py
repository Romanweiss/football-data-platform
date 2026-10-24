"""Explicit local-only S3 restore with a manually recovered PHONE key in memory.

No key-file option, source-service clients, vault access or network requests.
Default invocation does not open the key dialog or create any destination.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.recovery.runtime import RecoveryError


def _run_gui(args):
    import tkinter as tk
    from tkinter import messagebox
    from src.recovery.s3_offline_restore import phone_key, plan_restore, restore_local

    result = {'status': 'CANCELLED_NO_RESTORE'}
    window = tk.Tk()
    value, phone, visible = tk.StringVar(), tk.BooleanVar(), tk.BooleanVar()
    window.title('Football Platform - OFFLINE RESTORE / PHONE KEY')
    window.geometry('760x390')
    tk.Label(window, text='Read the PRODUCTION note on your PHONE. Do not open the original key file.\n'
             'Never enter a Bitwarden password, MFA code or recovery code.\n\n'
             + 'Session: ' + args.expect_session + '\nDestination: ' + str(args.destination),
             wraplength=730).pack(pady=18)
    entry = tk.Entry(window, textvariable=value, show='*', width=70)
    entry.pack(pady=8)
    tk.Checkbutton(window, text='Show input (do not share screenshots)', variable=visible,
                   command=lambda: entry.configure(show='' if visible.get() else '*')).pack()
    tk.Checkbutton(window, text='I obtained key_hex from Bitwarden ON THE PHONE.', variable=phone).pack()
    tk.Label(window, text='No key is saved. A final confirmation is required after offline authentication.').pack(pady=8)

    def submit():
        nonlocal result
        key = None
        try:
            key = phone_key(value.get(), phone_attested=phone.get())
            value.set('')
            visible.set(False)
            entry.configure(show='*')
            plan = plan_restore(args.archive, key, args.destination,
                                expected_session=args.expect_session, phone_attested=True)
            proceed = messagebox.askyesno('Authenticated offline restore plan',
                        f"Objects: {plan['source_objects']}\nBytes: {plan['source_bytes']}\n"
                        'Write decrypted sensitive payloads into the NEW private destination now?')
            if not proceed:
                window.destroy()
                return
            result = restore_local(args.archive, key, args.destination, expected_session=args.expect_session,
                                   confirmed=True, phone_attested=True, independent_media_confirmed=True)
            messagebox.showinfo('Offline restore', 'Restore and payload SHA-256 verification PASS. Close and return to chat.')
            window.destroy()
        except Exception:
            # No raw exception or key text in Tk callbacks, dialogs or console.
            result = {'status': 'FAIL', 'error': 'S3_OFFLINE_RESTORE_FAILED_PARTIAL_OUTPUT_RETAINED'}
            messagebox.showerror('Offline restore', 'Restore failed. No automatic retry. Retain any partial output and report FAIL.')
            window.destroy()
        finally:
            key = None
            try:
                value.set('')
            except Exception:
                pass

    def callback_failed(*_):
        nonlocal result
        result = {'status': 'FAIL', 'error': 'S3_OFFLINE_RESTORE_GUI_FAILED'}
        window.destroy()

    window.report_callback_exception = callback_failed
    tk.Button(window, text='Authenticate offline, then confirm restore', command=submit).pack(pady=16)
    try:
        entry.focus_set()
        window.mainloop()
    finally:
        try:
            value.set('')
            window.destroy()
        except Exception:
            pass
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--expect-session', required=True)
    parser.add_argument('--confirm-restore', action='store_true')
    parser.add_argument('--confirm-phone-key', action='store_true')
    parser.add_argument('--confirm-independent-media', action='store_true')
    args = parser.parse_args(argv)
    if not (args.confirm_restore and args.confirm_phone_key and args.confirm_independent_media):
        print(json.dumps({'status': 'BLOCKED', 'error': 'S3_RESTORE_CONFIRMATIONS_REQUIRED'}))
        return 1
    try:
        from src.recovery.s3_offline_restore import _session, check_paths
        _session(args.expect_session)
        check_paths(args.archive, args.destination)  # No dialog before safe path/media gates.
        result = _run_gui(args)
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0 if result.get('status', '').startswith('RESTORED_') else 1
    except KeyboardInterrupt:
        print('{"status":"INTERRUPTED_PARTIAL_OUTPUT_RETAINED"}', file=sys.stderr)
        return 130
    except Exception as exc:
        print(json.dumps({'status': 'FAIL', 'error': str(exc) if isinstance(exc, RecoveryError)
                          else 'S3_OFFLINE_RESTORE_FAILED'}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
