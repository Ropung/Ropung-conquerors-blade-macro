class HotkeyManager:
    def __init__(self, callbacks):
        import keyboard
        self.keyboard = keyboard
        self.handles = []
        try:
            for key, callback in callbacks.items():
                self.handles.append(keyboard.add_hotkey(key, callback, suppress=False, trigger_on_release=False))
        except Exception:
            self.close()
            raise

    def close(self):
        for handle in self.handles:
            self.keyboard.remove_hotkey(handle)
        self.handles.clear()
