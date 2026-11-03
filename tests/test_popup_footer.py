"""The confirmation action row remains inside its window on a real display."""


def test_confirm_buttons_visible_at_normal_screen_scale():
    import customtkinter as ctk
    from conftest import make_window
    from ui import components as C

    root = make_window(ctk.CTk)
    root.geometry("700x500+0+0")
    root.update()
    checked = []

    def walk(widget):
        for child in widget.winfo_children():
            yield child
            yield from walk(child)

    def inspect_and_cancel():
        dialogs = [w for w in root.winfo_children() if isinstance(w, ctk.CTkToplevel)]
        assert dialogs
        dialog = dialogs[-1]
        dialog.update_idletasks()
        buttons = {w.cget("text"): w for w in walk(dialog) if isinstance(w, ctk.CTkButton)}
        assert {"Cancel", "Confirm"} <= buttons.keys()
        for button in (buttons["Cancel"], buttons["Confirm"]):
            assert button.winfo_ismapped()
            assert button.winfo_rooty() + button.winfo_height() <= dialog.winfo_rooty() + dialog.winfo_height()
        checked.append(True)
        buttons["Cancel"].invoke()

    root.after(200, inspect_and_cancel)
    # Fail closed if a Tk implementation doesn't display the dialog.
    root.after(2500, lambda: [w.destroy() for w in root.winfo_children() if isinstance(w, ctk.CTkToplevel)])
    try:
        assert C.confirm("Add", "Add 2.5 kg of nails to this project?", parent=root) is False
        assert checked
    finally:
        root.destroy()
