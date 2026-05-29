class D3Profiler:
    def __init__(self, log_path="logs/corelang_d3_profile.log"):
        self.log_path = log_path
    def observe(self, text: str):
        if not isinstance(text, str) or not text: return
        import os
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(text.replace("\n"," ").strip()+"\n")