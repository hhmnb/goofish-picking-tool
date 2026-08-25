# gui.py
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import asyncio
import queue
import webbrowser
import logging
import csv
import re
import json
from pathlib import Path
from config import *
from logger import logger
from crawler import GoofishCrawler
from utils import extract_item_id


class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        self.log_queue.put(self.format(record))


class GoofishGUI:
    def __init__(self, root):
        self.root = root
        root.title("闲鱼选品审核工具")
        root.geometry("1000x900")
        root.minsize(800, 700)

        self.all_items = []
        self.display_items = []
        self.last_keyword = ""
        self.last_start_page = 1
        self.last_max_pages = 10
        self.template_content = ""
        self.filtering = False

        self.blacklist_ids = set()
        self.blacklist_names = set()
        self.load_blacklist()

        self.filter_mode_var = tk.StringVar(value="both")
        self.model_keywords = []

        self.config_file = Path(__file__).parent / "filter_configs.json"
        self.filter_configs = {}
        self.current_config_name = ""
        self.load_filter_configs()

        self.web_server = None
        self.log_queue = queue.Queue()
        self._setup_logging()

        root.configure(bg=BG_DEEP_BLUE)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(6, weight=3)
        root.rowconfigure(7, weight=1)
        root.rowconfigure(8, weight=2)

        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure("Treeview", background=BG_CONTAINER, foreground=TEXT_WHITE, fieldbackground=BG_CONTAINER)
        style.configure("Treeview.Heading", background=BG_DEEP_BLUE, foreground=TEXT_CYAN, relief="flat")
        style.map("Treeview", background=[("selected", "#0052CC")], foreground=[("selected", TEXT_WHITE)])

        self._build_widgets()
        self._load_template()
        self._check_login_status()

    def _setup_logging(self):
        for handler in logger.handlers[:]:
            if isinstance(handler, QueueHandler):
                logger.removeHandler(handler)
        queue_handler = QueueHandler(self.log_queue)
        queue_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(queue_handler)
        self.root.after(100, self._poll_log_queue)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_box.insert(tk.END, msg + '\n')
                self.log_box.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_log_queue)

    # ========== 配置方案管理 ==========
    def load_filter_configs(self):
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    logger.warning("检测到配置文件为列表格式，自动转换为标准字典格式")
                    self.filter_configs = {
                        "全局精细捡漏": {
                            "keyword": "捡漏",
                            "filter_mode": "price",
                            "models": data
                        }
                    }
                    self.save_filter_configs()
                elif isinstance(data, dict):
                    self.filter_configs = data
                else:
                    logger.error("配置文件格式不支持，使用空配置")
                    self.filter_configs = {}
                logger.info(f"已加载 {len(self.filter_configs)} 个过滤配置方案")
            except Exception as e:
                logger.error(f"加载过滤配置失败: {e}")
                self.filter_configs = {}
        else:
            logger.info("过滤配置文件不存在，使用空配置")

    def save_filter_configs(self):
        if not isinstance(self.filter_configs, dict):
            logger.error("尝试保存非字典类型的配置，已阻止")
            return
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.filter_configs, f, ensure_ascii=False, indent=2)
            logger.info(f"已保存 {len(self.filter_configs)} 个过滤配置方案")
        except Exception as e:
            logger.error(f"保存过滤配置失败: {e}")

    def get_current_config_dict(self):
        config = {
            "keyword": self.keyword_entry.get().strip(),
            "filter_mode": self.filter_mode_var.get(),
            "min_price": self.min_price_entry.get().strip(),
            "max_price": self.max_price_entry.get().strip(),
            "model_keywords": self._parse_model_keywords(self.model_keywords_text.get("1.0", tk.END))
        }
        return config

    def load_config_to_ui(self, config_name):
        if config_name not in self.filter_configs:
            messagebox.showwarning("提示", f"配置 '{config_name}' 不存在")
            return
        config = self.filter_configs[config_name]
        self.keyword_entry.delete(0, tk.END)
        self.keyword_entry.insert(0, config.get("keyword", ""))
        self.filter_mode_var.set(config.get("filter_mode", "both"))

        if "models" in config:
            all_keywords = []
            for model in config["models"]:
                all_keywords.extend(model.get("keywords", []))
            self.model_keywords_text.delete("1.0", tk.END)
            self.model_keywords_text.insert("1.0", "\n".join(dict.fromkeys(all_keywords)))
            self.min_price_entry.delete(0, tk.END)
            self.max_price_entry.delete(0, tk.END)
        else:
            self.min_price_entry.delete(0, tk.END)
            self.min_price_entry.insert(0, config.get("min_price", ""))
            self.max_price_entry.delete(0, tk.END)
            self.max_price_entry.insert(0, config.get("max_price", ""))
            self.model_keywords_text.delete("1.0", tk.END)
            self.model_keywords_text.insert("1.0", "\n".join(config.get("model_keywords", [])))

        self.current_config_name = config_name
        self._update_config_combo()
        logger.info(f"已加载配置: {config_name}")
        self.refresh_display_with_filters()

    def _parse_model_keywords(self, text):
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        keywords = []
        for line in lines:
            parts = re.split(r'[,，]', line)
            for p in parts:
                p = p.strip()
                if p:
                    keywords.append(p)
        return keywords

    def _apply_model_filter(self, items):
        keywords = self._parse_model_keywords(self.model_keywords_text.get("1.0", tk.END))
        if not keywords:
            return items
        filtered = []
        for item in items:
            title = item.get("title", "")
            if any(kw in title for kw in keywords):
                filtered.append(item)
        return filtered

    def save_current_config(self):
        config = self.get_current_config_dict()
        if not config["keyword"]:
            messagebox.showwarning("提示", "请先输入关键词")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("保存配置")
        dialog.geometry("400x200")
        dialog.configure(bg=BG_DEEP_BLUE)
        tk.Label(dialog, text="配置名称:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack(pady=10)
        name_entry = tk.Entry(dialog, width=30, bg=BG_CONTAINER, fg=TEXT_WHITE, insertbackground=TEXT_WHITE)
        name_entry.pack(pady=5)
        name_entry.insert(0, config["keyword"])
        name_entry.focus()

        def confirm():
            name = name_entry.get().strip()
            if not name:
                messagebox.showwarning("提示", "名称不能为空")
                return
            self.filter_configs[name] = config
            self.save_filter_configs()
            self.current_config_name = name
            self._update_config_combo()
            dialog.destroy()
            messagebox.showinfo("成功", f"配置 '{name}' 已保存")

        tk.Button(dialog, text="确定", command=confirm, bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(pady=10)

    def load_config_dialog(self):
        if not self.filter_configs:
            messagebox.showinfo("提示", "暂无保存的配置方案")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("加载配置")
        dialog.geometry("400x400")
        dialog.configure(bg=BG_DEEP_BLUE)

        tk.Label(dialog, text="选择配置:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack(pady=10)
        listbox = tk.Listbox(dialog, bg=BG_CONTAINER, fg=TEXT_WHITE, font=("Consolas", 12))
        listbox.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        for name in sorted(self.filter_configs.keys()):
            listbox.insert(tk.END, name)

        def load_selected():
            selection = listbox.curselection()
            if selection:
                name = listbox.get(selection[0])
                dialog.destroy()
                self.load_config_to_ui(name)
            else:
                messagebox.showwarning("提示", "请选择配置")

        tk.Button(dialog, text="加载", command=load_selected, bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(pady=5)
        tk.Button(dialog, text="取消", command=dialog.destroy, bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).pack(pady=5)

    def delete_config(self):
        name = self.config_combo.get()
        if not name:
            messagebox.showwarning("提示", "请先从下拉框中选择要删除的配置")
            return
        if name not in self.filter_configs:
            messagebox.showwarning("提示", f"配置 '{name}' 不存在")
            return
        if not messagebox.askyesno("确认删除", f"确定要删除配置 '{name}' 吗？"):
            return
        del self.filter_configs[name]
        self.save_filter_configs()
        if self.current_config_name == name:
            self.current_config_name = ""
        self._update_config_combo()
        logger.info(f"已删除配置: {name}")
        messagebox.showinfo("成功", f"配置 '{name}' 已删除")

    def auto_load_config_for_keyword(self, keyword):
        keyword_lower = keyword.lower().strip()
        if not keyword_lower:
            return

        best_match = None

        # 第一优先级：配置的 keyword 字段完全匹配或包含搜索词
        for name, config in self.filter_configs.items():
            cfg_keyword = config.get("keyword", "").lower().strip()
            if cfg_keyword == keyword_lower:
                best_match = name
                break
            elif cfg_keyword and cfg_keyword in keyword_lower:
                if best_match is None:
                    best_match = name

        # 第二优先级：搜索词与配置中任何机型关键词部分匹配
        if not best_match:
            for name, config in self.filter_configs.items():
                models = config.get("models", [])
                for model in models:
                    for kw in model.get("keywords", []):
                        kw_lower = kw.lower()
                        # 互相包含关系（例如搜索“cpu”匹配“R5 5600”中的“R5”？可能不够准确，建议改为仅检查关键词是否包含搜索词，或搜索词包含关键词）
                        if kw_lower in keyword_lower or keyword_lower in kw_lower:
                            best_match = name
                            break
                    if best_match:
                        break
                if best_match:
                    break

        if best_match:
            self.load_config_to_ui(best_match)
            logger.info(f"关键词 '{keyword}' 自动匹配配置: {best_match}")
        else:
            logger.info(f"关键词 '{keyword}' 未找到匹配配置")

    def _update_config_combo(self):
        if not isinstance(self.filter_configs, dict):
            self.filter_configs = {}
        names = list(self.filter_configs.keys())
        self.config_combo['values'] = names
        if self.current_config_name and self.current_config_name in names:
            self.config_combo.set(self.current_config_name)
        else:
            self.config_combo.set('')

    # ========== 导出AI提示词 ==========
    def export_ai_prompt(self):
        prompt = (
            "请根据以下商品行情数据，生成一个 JSON 数组，格式为：\n"
            '[{"keywords": ["机型关键词1", "机型关键词2"], "min_price": "最低捡漏价", "max_price": "最高捡漏价"}, ...]\n\n'
            "规则：\n"
            "1. keywords 为数组，至少包含一个关键词，用于匹配商品标题。建议包含带空格和不带空格的常见写法；"
            "如果同一机型存在多个内存/存储版本（如 256G、512G、12+512G），务必在关键词中体现版本差异，并分别生成条目。\n"
            "2. min_price 和 max_price 为字符串数字，价格区间直接使用文本中给出的价格，不要进行任何折扣或加价计算。\n"
            "3. 只输出 JSON 数组，不要包含任何解释文字、代码块标记或其他内容。\n\n"
            "请开始："
        )
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.root.update()
        logger.info("AI提示词已复制到剪贴板")
        messagebox.showinfo("成功", "AI提示词已复制到剪贴板，请直接粘贴给AI使用。\n\n提示词内容：\n" + prompt)

    # ========== 从文本快速生成配置（自动合并到全局配置） ==========
    def analyze_text_to_config(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("从文本生成配置")
        dialog.geometry("700x600")
        dialog.configure(bg=BG_DEEP_BLUE)

        tip_text = (
            "支持两种格式：\n"
            "1. JSON数组（推荐，最准确）：\n"
            '[{"keywords": ["机型关键词1", "机型关键词2"], "min_price": "最低捡漏价", "max_price": "最高捡漏价"}, ...]\n'
            "2. 普通文本（表格或列表）：\n"
            "型号 | 参考价\n"
            "iPhone 13 Pro 256G | 1300-1500元\n"
            "或：小米13 128G 800元\n\n"
            "注意：程序将直接采用文本中的价格，不做任何折扣。"
        )
        tk.Label(dialog, text=tip_text, bg=BG_DEEP_BLUE, fg=TEXT_CYAN,
                 justify=tk.LEFT, font=("微软雅黑", 9)).pack(pady=5, padx=10, anchor="w")

        tk.Label(dialog, text="请粘贴内容：", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack(anchor="w", padx=10)
        text_area = scrolledtext.ScrolledText(dialog, height=15, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                              insertbackground=TEXT_WHITE, relief=tk.FLAT)
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        def analyze():
            content = text_area.get("1.0", tk.END).strip()
            if not content:
                messagebox.showwarning("提示", "文本为空")
                return

            models = self._parse_models_from_text(content)
            if models:
                global_config_name = "全局精细捡漏"
                if global_config_name in self.filter_configs:
                    existing_models = self.filter_configs[global_config_name].get("models", [])
                    for new_model in models:
                        duplicate = False
                        for existing_model in existing_models:
                            if set(new_model.get("keywords", [])) == set(existing_model.get("keywords", [])):
                                duplicate = True
                                break
                        if not duplicate:
                            existing_models.append(new_model)
                    self.filter_configs[global_config_name]["models"] = existing_models
                    self.save_filter_configs()
                    self.current_config_name = global_config_name
                    self._update_config_combo()
                    self.refresh_display_with_filters()
                    dialog.destroy()
                    messagebox.showinfo("完成", f"已合并 {len(models)} 个机型到全局配置 '{global_config_name}'")
                    logger.info(f"从文本合并到全局配置: {global_config_name}, 新增 {len(models)} 个机型")
                    return
                else:
                    config = {
                        "keyword": self.keyword_entry.get().strip() or "全局捡漏",
                        "filter_mode": "price",
                        "models": models
                    }
                    self.filter_configs[global_config_name] = config
                    self.save_filter_configs()
                    self.current_config_name = global_config_name
                    self._update_config_combo()
                    self.refresh_display_with_filters()
                    dialog.destroy()
                    messagebox.showinfo("完成", f"已创建全局配置 '{global_config_name}'，包含 {len(models)} 个机型")
                    logger.info(f"创建全局精细配置: {global_config_name}, models数量: {len(models)}")
                    return

            # 原有统一价格区间生成逻辑（此时价格直接采用原文）
            min_price, max_price = self._extract_price_range_from_text(content)
            model_keywords = self._extract_model_keywords_from_text(content)

            if min_price is not None:
                self.min_price_entry.delete(0, tk.END)
                self.min_price_entry.insert(0, f"{min_price:.0f}")
            if max_price is not None:
                self.max_price_entry.delete(0, tk.END)
                self.max_price_entry.insert(0, f"{max_price:.0f}")
            if model_keywords:
                self.model_keywords_text.delete("1.0", tk.END)
                self.model_keywords_text.insert("1.0", "\n".join(model_keywords))

            if self.keyword_entry.get().strip():
                config_name = self.keyword_entry.get().strip()
            elif model_keywords:
                config_name = model_keywords[0]
            else:
                config_name = "自动生成配置"

            original_name = config_name
            counter = 1
            while config_name in self.filter_configs:
                config_name = f"{original_name}_{counter}"
                counter += 1

            config = self.get_current_config_dict()
            self.filter_configs[config_name] = config
            self.save_filter_configs()
            self.current_config_name = config_name
            self._update_config_combo()
            self.refresh_display_with_filters()

            dialog.destroy()
            messagebox.showinfo("完成",
                f"已生成配置 '{config_name}'\n价格区间: {min_price}-{max_price}\n机型关键词: {', '.join(model_keywords)}")
            logger.info(f"从文本生成并保存配置: {config_name}, 价格 {min_price}-{max_price}, 机型 {model_keywords}")

        tk.Button(dialog, text="分析并保存配置", command=analyze, bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(pady=10)

    def _parse_models_from_text(self, text):
        """解析文本，生成 models 列表。支持 JSON 数组、Markdown 表格和普通列表。"""
        stripped = text.strip()
        # 优先解析 JSON 数组
        if stripped.startswith('[') and stripped.endswith(']'):
            try:
                data = json.loads(stripped)
                if isinstance(data, list):
                    models = []
                    for item in data:
                        if isinstance(item, dict) and "keywords" in item and "min_price" in item and "max_price" in item:
                            models.append(item)
                    return models
            except json.JSONDecodeError:
                pass  # 不是合法 JSON，继续尝试其它格式

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return []

        # 1) 尝试解析表格
        models = self._parse_table_models(lines)
        if models:
            return models

        # 2) 尝试解析普通列表文本
        models = self._parse_list_models(text)
        return models

    def _parse_table_models(self, lines):
        if not any('|' in line for line in lines):
            return []
        header_idx = None
        for i, line in enumerate(lines):
            if '|' in line and ('型号' in line or '参考价' in line or '价格' in line):
                header_idx = i
                break
        if header_idx is None:
            return []
        header_fields = [f.strip() for f in lines[header_idx].split('|') if f.strip()]
        model_idx = None
        price_idx = None
        for idx, field in enumerate(header_fields):
            if '型号' in field:
                model_idx = idx
            if '参考价' in field or '价格' in field:
                price_idx = idx
        if model_idx is None or price_idx is None:
            return []
        models = []
        for line in lines[header_idx+1:]:
            if '|' not in line:
                continue
            fields = [f.strip() for f in line.split('|') if f.strip()]
            if len(fields) <= max(model_idx, price_idx):
                continue
            model_text = fields[model_idx] if model_idx < len(fields) else ''
            price_text = fields[price_idx] if price_idx < len(fields) else ''
            if not model_text or not price_text:
                continue
            price_match = re.search(r'(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)\s*(?:元|块|¥|￥)?', price_text)
            if not price_match:
                continue
            price = float(price_match.group(1))
            if price <= 0:
                continue
            range_match = re.search(r'(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)\s*[-~到至]\s*(\d{3,5}(?:\.\d{1,2})?)\s*(?:元|块|¥|￥)?', price_text)
            if range_match:
                min_ref = float(range_match.group(1))
                max_ref = float(range_match.group(2))
            else:
                min_ref = max_ref = price
            keywords = self._extract_model_keywords_from_text(model_text)
            if not keywords:
                keywords = [model_text]
            # 不进行折扣，直接采用原文价格
            min_p = str(int(min_ref))
            max_p = str(int(max_ref))
            models.append({
                "keywords": keywords,
                "min_price": min_p,
                "max_price": max_p
            })
        return models

    def _parse_list_models(self, text):
        models = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # 优先匹配带价格单位的数字
            unit_price_pattern = r'(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)\s*(?:元|块|¥|￥)'
            unit_matches = list(re.finditer(unit_price_pattern, line))
            if unit_matches:
                price_match = unit_matches[-1]
                price = float(price_match.group(1))
                line_clean = line[:price_match.start()] + line[price_match.end():]
            else:
                price_pattern = r'(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)(?![\w.])'
                price_matches = list(re.finditer(price_pattern, line))
                if not price_matches:
                    continue
                price_match = price_matches[-1]
                price = float(price_match.group(1))
                line_clean = line[:price_match.start()] + line[price_match.end():]
            keywords = self._extract_model_keywords_from_text(line_clean)
            if not keywords:
                keywords = [line_clean.strip()] if line_clean.strip() else []
            keywords = [kw for kw in keywords if kw]
            if not keywords:
                continue
            range_match = re.search(r'(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)\s*[-~到至]\s*(\d{3,5}(?:\.\d{1,2})?)\s*(?:元|块|¥|￥)?', line)
            if range_match:
                min_ref = float(range_match.group(1))
                max_ref = float(range_match.group(2))
                min_p = str(int(min_ref))
                max_p = str(int(max_ref))
            else:
                min_p = str(int(price))
                max_p = str(int(price))
            models.append({
                "keywords": keywords[:15],
                "min_price": min_p,
                "max_price": max_p
            })
        return models

    def _extract_price_range_from_text(self, text):
        min_price = None
        max_price = None
        patterns = [
            r'(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)\s*[-~到至]\s*(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)\s*元?',
            r'价格(?:在|区间)?\s*(\d{3,5}(?:\.\d{1,2})?)\s*[-~到至]\s*(\d{3,5}(?:\.\d{1,2})?)',
            r'(\d{3,5}(?:\.\d{1,2})?)\s*元\s*[-~到至]\s*(\d{3,5}(?:\.\d{1,2})?)\s*元'
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                min_price = float(match.group(1))
                max_price = float(match.group(2))
                if min_price > max_price:
                    min_price, max_price = max_price, min_price
                return min_price, max_price

        price_candidates = []
        price_pattern = r'(?<![\w.])(\d{3,5}(?:\.\d{1,2})?)\s*(?:元|块|¥|￥)?'
        matches = re.findall(price_pattern, text)
        for m in matches:
            val = float(m)
            if 10 <= val <= 50000:
                price_candidates.append(val)

        if len(price_candidates) >= 2:
            min_price = min(price_candidates)
            max_price = max(price_candidates)
        elif len(price_candidates) == 1:
            base = price_candidates[0]
            min_price = base
            max_price = base
        return min_price, max_price

    def _extract_model_keywords_from_text(self, text):
        # 仅移除容量单位，不删除普通数字
        text = re.sub(r'\d+\s*(?:GB|G|TB|T|MB|M|g|gb|t|tb|m|mb)', ' ', text, flags=re.IGNORECASE)
        keywords = []
        brand_pattern = r'(华为|荣耀|小米|红米|OPPO|vivo|苹果|iPhone|iPad|MacBook|iMac|Mac mini|Apple Watch|AirPods|三星|一加|realme|魅族|联想|摩托罗拉|中兴|努比亚|黑鲨|ROG|惠普|戴尔|联想|东芝|华硕|富士通|ThinkPad|拯救者|Redmi|Xiaomi|佳能|尼康|索尼|富士|松下|理光|宾得)\s*([A-Za-z0-9]+(?:\s*[A-Za-z0-9]+)*)'
        matches = re.findall(brand_pattern, text, re.IGNORECASE)
        for brand, model in matches:
            kw = (brand + " " + model).strip()
            kw_nospace = (brand + model).replace(" ", "")
            if re.search(r'\d+\s*(?:GB|G|TB|T|MB|M|g|gb|t|tb|m|mb)', kw, re.IGNORECASE):
                continue
            if kw not in keywords:
                keywords.append(kw)
            if kw_nospace not in keywords:
                keywords.append(kw_nospace)

        # 特殊型号（显卡/CPU）
        if not keywords:
            special_pattern = r'\b(RTX|GTX|RX|i\d|R\d)\s*[-]?\s*([A-Za-z0-9]+(?:\s*[A-Za-z0-9]+)*)'
            matches = re.findall(special_pattern, text, re.IGNORECASE)
            for prefix, model in matches:
                kw = (prefix + " " + model).strip()
                kw_nospace = (prefix + model).replace(" ", "")
                if kw not in keywords:
                    keywords.append(kw)
                if kw_nospace not in keywords:
                    keywords.append(kw_nospace)

        if not keywords:
            words = re.findall(r'[A-Za-z][A-Za-z0-9]{1,}(?:\s+[A-Za-z0-9]{1,})?', text)
            for w in words:
                w_clean = w.strip()
                if (len(w_clean) >= 3 and
                    not re.search(r'\d+\s*(?:GB|G|TB|T|MB|M|g|gb|t|tb|m|mb)', w_clean, re.IGNORECASE) and
                    w_clean.lower() not in ('手机', '价格', '元', '全新', '二手')):
                    keywords.append(w_clean)
        keywords = list(dict.fromkeys(keywords))[:15]
        return keywords

    def view_edit_config_file(self):
        if not self.config_file.exists():
            messagebox.showinfo("提示", "配置文件不存在，请先保存一个配置")
            return

        win = tk.Toplevel(self.root)
        win.title("查看/编辑配置文件")
        win.geometry("800x600")
        win.configure(bg=BG_DEEP_BLUE)

        text_area = scrolledtext.ScrolledText(win, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                              insertbackground=TEXT_WHITE, font=("Consolas", 11))
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                content = f.read()
            text_area.insert("1.0", content)
        except Exception as e:
            logger.error(f"读取配置文件失败: {e}")
            messagebox.showerror("错误", f"读取配置文件失败: {e}")
            win.destroy()
            return

        def save():
            new_content = text_area.get("1.0", tk.END).strip()
            try:
                data = json.loads(new_content)
                if not isinstance(data, dict):
                    messagebox.showerror("错误", "配置文件必须是字典格式，不能是列表")
                    return
                with open(self.config_file, "w", encoding="utf-8") as f:
                    f.write(new_content)
                self.load_filter_configs()
                self._update_config_combo()
                logger.info("配置文件已手动更新")
                messagebox.showinfo("成功", "配置文件已保存并重新加载")
                win.destroy()
            except json.JSONDecodeError as e:
                messagebox.showerror("JSON格式错误", f"JSON格式无效: {e}")

        btn_frame = tk.Frame(win, bg=BG_DEEP_BLUE)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Button(btn_frame, text="保存", command=save, bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="取消", command=win.destroy, bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)

    def _build_widgets(self):
        title = tk.Label(self.root, text="闲鱼选品审核工具", font=("微软雅黑", 16, "bold"),
                         bg=BG_DEEP_BLUE, fg=TEXT_CYAN)
        title.grid(row=0, column=0, pady=10)

        input_frame = tk.Frame(self.root, bg=BG_DEEP_BLUE)
        input_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=5)
        input_frame.columnconfigure(1, weight=1)
        tk.Label(input_frame, text="关键词:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=0, column=0)
        self.keyword_entry = tk.Entry(input_frame, width=30, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                      insertbackground=TEXT_WHITE, relief=tk.FLAT)
        self.keyword_entry.grid(row=0, column=1, sticky="ew", ipady=4)
        self.keyword_entry.focus()
        self.keyword_entry.bind("<FocusOut>", lambda e: self.auto_load_config_for_keyword(self.keyword_entry.get()))

        # 配置方案选择栏
        config_frame = tk.Frame(self.root, bg=BG_DEEP_BLUE)
        config_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=5)
        tk.Label(config_frame, text="配置方案:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack(side=tk.LEFT)
        self.config_combo = ttk.Combobox(config_frame, state="readonly", width=25)
        self.config_combo.pack(side=tk.LEFT, padx=5)
        self.config_combo.bind("<<ComboboxSelected>>", lambda e: self.load_config_to_ui(self.config_combo.get()))
        tk.Button(config_frame, text="保存当前配置", command=self.save_current_config,
                  bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(config_frame, text="加载配置", command=self.load_config_dialog,
                  bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(config_frame, text="删除配置", command=self.delete_config,
                  bg="#d9534f", fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(config_frame, text="从文本生成配置", command=self.analyze_text_to_config,
                  bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(config_frame, text="查看/编辑配置", command=self.view_edit_config_file,
                  bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(config_frame, text="导出AI提示词", command=self.export_ai_prompt,
                  bg="#5bc0de", fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        self._update_config_combo()

        # 选项区域
        option_frame = tk.Frame(self.root, bg=BG_DEEP_BLUE)
        option_frame.grid(row=3, column=0, sticky="ew", padx=20, pady=5)
        tk.Label(option_frame, text="起始页:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=0, column=0)
        self.start_page_spinbox = tk.Spinbox(option_frame, from_=1, to=100, width=4,
                                             bg=BG_CONTAINER, fg=TEXT_WHITE, relief=tk.FLAT)
        self.start_page_spinbox.grid(row=0, column=1)
        self.start_page_spinbox.delete(0, tk.END)
        self.start_page_spinbox.insert(0, "1")
        tk.Label(option_frame, text="爬取页数:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=0, column=2, padx=(20, 2))
        self.pages_spinbox = tk.Spinbox(option_frame, from_=1, to=50, width=4,
                                        bg=BG_CONTAINER, fg=TEXT_WHITE, relief=tk.FLAT)
        self.pages_spinbox.grid(row=0, column=3)
        self.pages_spinbox.delete(0, tk.END)
        self.pages_spinbox.insert(0, "10")

        self.filter_professional_var = tk.BooleanVar(value=True)
        tk.Checkbutton(option_frame, text="AI筛选后过滤专业商家(在售>20)",
                       variable=self.filter_professional_var, bg=BG_DEEP_BLUE, fg=TEXT_WHITE,
                       selectcolor=BG_CONTAINER, activebackground=BG_DEEP_BLUE,
                       activeforeground=TEXT_CYAN).grid(row=0, column=4, padx=(20, 0))

        # 过滤模式选择
        tk.Label(option_frame, text="过滤模式:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=1, column=0, pady=(5, 0), sticky="e")
        modes_frame = tk.Frame(option_frame, bg=BG_DEEP_BLUE)
        modes_frame.grid(row=1, column=1, columnspan=4, pady=(5, 0), sticky="w")
        tk.Radiobutton(modes_frame, text="黑名单过滤", variable=self.filter_mode_var, value="blacklist",
                       bg=BG_DEEP_BLUE, fg=TEXT_WHITE, selectcolor=BG_CONTAINER,
                       activebackground=BG_DEEP_BLUE, activeforeground=TEXT_CYAN).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(modes_frame, text="价格过滤", variable=self.filter_mode_var, value="price",
                       bg=BG_DEEP_BLUE, fg=TEXT_WHITE, selectcolor=BG_CONTAINER,
                       activebackground=BG_DEEP_BLUE, activeforeground=TEXT_CYAN).pack(side=tk.LEFT, padx=5)
        tk.Radiobutton(modes_frame, text="价格+黑名单", variable=self.filter_mode_var, value="both",
                       bg=BG_DEEP_BLUE, fg=TEXT_WHITE, selectcolor=BG_CONTAINER,
                       activebackground=BG_DEEP_BLUE, activeforeground=TEXT_CYAN).pack(side=tk.LEFT, padx=5)

        # 价格区间输入
        tk.Label(option_frame, text="价格区间:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=2, column=0, pady=(5, 0), sticky="e")
        self.min_price_entry = tk.Entry(option_frame, width=10, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                        insertbackground=TEXT_WHITE, relief=tk.FLAT)
        self.min_price_entry.grid(row=2, column=1, pady=(5, 0), sticky="w")
        tk.Label(option_frame, text="~", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=2, column=2, pady=(5, 0))
        self.max_price_entry = tk.Entry(option_frame, width=10, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                        insertbackground=TEXT_WHITE, relief=tk.FLAT)
        self.max_price_entry.grid(row=2, column=3, pady=(5, 0), sticky="w")
        tk.Label(option_frame, text="(留空不限)", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=2, column=4, pady=(5, 0), sticky="w")
        self.min_price_entry.bind("<Return>", lambda e: self.refresh_display_with_filters())
        self.max_price_entry.bind("<Return>", lambda e: self.refresh_display_with_filters())

        # 机型关键词输入
        tk.Label(option_frame, text="机型关键词:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(row=3, column=0, pady=(5, 0), sticky="ne")
        self.model_keywords_text = tk.Text(option_frame, height=3, width=60, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                           insertbackground=TEXT_WHITE, relief=tk.FLAT)
        self.model_keywords_text.grid(row=3, column=1, columnspan=4, pady=(5, 0), sticky="ew")
        tk.Label(option_frame, text="(每行一个，或逗号分隔)", bg=BG_DEEP_BLUE, fg=TEXT_CYAN).grid(row=4, column=1, columnspan=4, sticky="w")

        # 按钮区域
        btn_frame = tk.Frame(self.root, bg=BG_DEEP_BLUE)
        btn_frame.grid(row=4, column=0, sticky="ew", padx=20, pady=5)
        for i in range(6):
            btn_frame.columnconfigure(i, weight=1)

        self.search_btn = tk.Button(btn_frame, text="🔍 开始采集", command=self.start_search,
                                    bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT)
        self.search_btn.grid(row=0, column=0, padx=5, sticky="ew")

        self.login_btn = tk.Button(btn_frame, text="🔑 登录闲鱼", command=self.login_goofish,
                                   bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT)
        self.login_btn.grid(row=0, column=1, padx=5, sticky="ew")

        self.copy_all_btn = tk.Button(btn_frame, text="📋 复制全部数据", command=self.copy_all_data,
                                      bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT)
        self.copy_all_btn.grid(row=0, column=2, padx=5, sticky="ew")

        self.show_all_btn = tk.Button(btn_frame, text="🔄 显示全部", command=self.show_all_items,
                                      bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT)
        self.show_all_btn.grid(row=0, column=3, padx=5, sticky="ew")

        self.edit_template_btn = tk.Button(btn_frame, text="✏️ 编辑提示词", command=self.open_template_editor,
                                           bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT)
        self.edit_template_btn.grid(row=0, column=4, padx=5, sticky="ew")

        self.web_ui_btn = tk.Button(btn_frame, text="🌐 网页界面", command=self.open_web_ui,
                                    bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT)
        self.web_ui_btn.grid(row=0, column=5, padx=5, sticky="ew")

        # 信息标签
        self.info_var = tk.StringVar(value="尚未采集")
        tk.Label(self.root, textvariable=self.info_var, bg=BG_DEEP_BLUE, fg=TEXT_CYAN).grid(
            row=5, column=0, sticky="w", padx=20, pady=(0, 5))

        # 商品列表区域
        list_frame = tk.Frame(self.root, bg=BG_DEEP_BLUE)
        list_frame.grid(row=7, column=0, sticky="nsew", padx=20, pady=(0, 5))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)

        # 筛选栏
        filter_bar = tk.Frame(list_frame, bg=BG_DEEP_BLUE)
        filter_bar.grid(row=0, column=0, sticky="ew", pady=(0, 5))

        tk.Label(filter_bar, text="商品列表（双击打开链接）:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack(side=tk.LEFT)

        self.seller_filter_entry = tk.Entry(filter_bar, width=20, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                            insertbackground=TEXT_WHITE, relief=tk.FLAT)
        self.seller_filter_entry.pack(side=tk.LEFT, padx=(10, 5))
        self.seller_filter_entry.bind("<Return>", lambda e: self.filter_by_seller_name())

        tk.Button(filter_bar, text="🔍 筛选商家", command=self.filter_by_seller_name,
                  bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Button(filter_bar, text="纯数字昵称", command=self.filter_numeric_sellers,
                  bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Button(filter_bar, text="空昵称", command=self.filter_empty_sellers,
                  bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=2)

        tk.Button(filter_bar, text="☑ 全选", command=self.select_all_tree_items,
                  bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=10)

        # 商品树
        columns = ("title", "price", "seller", "link")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12, selectmode="extended")
        self.tree.heading("title", text="商品标题")
        self.tree.heading("price", text="价格")
        self.tree.heading("seller", text="卖家")
        self.tree.heading("link", text="链接")
        self.tree.column("title", width=420, anchor="w", stretch=True)
        self.tree.column("price", width=80, anchor="center", stretch=False)
        self.tree.column("seller", width=120, anchor="w", stretch=False)
        self.tree.column("link", width=180, anchor="w", stretch=False)
        self.tree.grid(row=1, column=0, sticky="nsew")

        v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.tree.yview)
        v_scrollbar.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=v_scrollbar.set)

        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        h_scrollbar.grid(row=2, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=h_scrollbar.set)

        self.tree.bind("<Double-1>", self.open_selected_link)

        # 操作按钮行
        action_frame = tk.Frame(list_frame, bg=BG_DEEP_BLUE)
        action_frame.grid(row=3, column=0, sticky="w", pady=(5, 0))
        tk.Button(action_frame, text="打开选中商品", command=self.open_selected_link,
                  bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(action_frame, text="拉黑选中卖家", command=self.blacklist_selected_seller,
                  bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(action_frame, text="管理黑名单", command=self.manage_blacklist_window,
                  bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT)

        # AI 结果处理区域
        ai_frame = tk.Frame(self.root, bg=BG_DEEP_BLUE)
        ai_frame.grid(row=8, column=0, sticky="ew", padx=20, pady=5)
        ai_frame.columnconfigure(1, weight=1)
        tk.Label(ai_frame, text="AI审核结果:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(
            row=0, column=0, sticky="nw")
        self.ai_text = scrolledtext.ScrolledText(ai_frame, height=6, bg=BG_CONTAINER,
                                                 fg=TEXT_WHITE, insertbackground=TEXT_WHITE, relief=tk.FLAT)
        self.ai_text.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        tk.Button(ai_frame, text="应用AI筛选", command=self.apply_ai_filter,
                  bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT).grid(row=0, column=2, padx=(5, 0))

        # 日志区域
        log_frame = tk.Frame(self.root, bg=BG_DEEP_BLUE)
        log_frame.grid(row=9, column=0, sticky="nsew", padx=20, pady=(5, 10))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        tk.Label(log_frame, text="运行日志:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).grid(
            row=0, column=0, sticky="w")
        self.log_box = scrolledtext.ScrolledText(log_frame, height=8, bg=BG_CONTAINER,
                                                 fg=TEXT_WHITE, insertbackground=TEXT_WHITE, relief=tk.FLAT)
        self.log_box.grid(row=1, column=0, sticky="nsew")

    # ========== 快速筛选功能 ==========
    def filter_by_seller_name(self):
        keyword = self.seller_filter_entry.get().strip().lower()
        if not keyword:
            messagebox.showinfo("提示", "请输入筛选关键词")
            return
        self.display_items = [
            item for item in self.all_items
            if keyword in str(item.get("seller_name", "")).lower() or keyword in str(item.get("seller_id", "")).lower()
        ]
        self.refresh_tree()
        self.info_var.set(f"筛选结果：{len(self.display_items)} 个商品（关键词: {keyword}）")
        logger.info(f"按关键词筛选完成，匹配 {len(self.display_items)} 个商品")

    def filter_numeric_sellers(self):
        self.display_items = [
            item for item in self.all_items
            if str(item.get("seller_name", "")).isdigit()
        ]
        self.refresh_tree()
        self.info_var.set(f"纯数字昵称卖家：{len(self.display_items)} 个商品")
        logger.info(f"筛选出纯数字昵称商品 {len(self.display_items)} 个")

    def filter_empty_sellers(self):
        self.display_items = [
            item for item in self.all_items
            if not item.get("seller_name") or not str(item.get("seller_name", "")).strip()
        ]
        self.refresh_tree()
        self.info_var.set(f"空昵称卖家：{len(self.display_items)} 个商品")
        logger.info(f"筛选出空昵称商品 {len(self.display_items)} 个")

    def select_all_tree_items(self):
        all_items = self.tree.get_children()
        if all_items:
            self.tree.selection_set(all_items)
            logger.info("已全选当前列表商品")
        else:
            messagebox.showinfo("提示", "列表为空")

    # ---------- 黑名单管理 ----------
    def load_blacklist(self):
        self.blacklist_ids = set()
        self.blacklist_names = set()
        if BLACKLIST_FILE.exists():
            try:
                with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
                    raw_lines = [line.strip() for line in f if line.strip()]
                for line in raw_lines:
                    if line.isdigit():
                        self.blacklist_ids.add(line)
                    else:
                        self.blacklist_names.add(line)
                logger.info(f"已加载黑名单：ID {len(self.blacklist_ids)} 个，昵称 {len(self.blacklist_names)} 个")
            except Exception as e:
                logger.error(f"读取黑名单失败: {e}")
        else:
            logger.info("黑名单文件不存在，使用空黑名单")

    def save_blacklist(self):
        try:
            with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
                for sid in self.blacklist_ids:
                    f.write(sid + "\n")
                for name in self.blacklist_names:
                    f.write(name + "\n")
            logger.info(f"黑名单已保存，ID {len(self.blacklist_ids)} 个，昵称 {len(self.blacklist_names)} 个")
        except Exception as e:
            logger.error(f"保存黑名单失败: {e}")

    def _get_price_range(self):
        min_str = self.min_price_entry.get().strip()
        max_str = self.max_price_entry.get().strip()
        min_price = None
        max_price = None
        try:
            if min_str:
                min_price = float(min_str)
        except ValueError:
            logger.warning(f"最低价格式错误: {min_str}，忽略")
        try:
            if max_str:
                max_price = float(max_str)
        except ValueError:
            logger.warning(f"最高价格式错误: {max_str}，忽略")
        return min_price, max_price

    def _apply_price_filter(self, items):
        min_price, max_price = self._get_price_range()
        if min_price is None and max_price is None:
            return items
        filtered = []
        for item in items:
            price_str = item.get("price", "")
            try:
                price = float(re.sub(r'[^\d.]', '', price_str))
            except (ValueError, TypeError):
                continue
            if min_price is not None and price < min_price:
                continue
            if max_price is not None and price > max_price:
                continue
            filtered.append(item)
        return filtered

    def _apply_blacklist_only(self, items):
        filtered = []
        for item in items:
            sid = item.get("seller_id", "")
            sname = item.get("seller_name", "")

            # 只根据黑名单集合过滤，不再自动过滤空昵称/纯数字
            if sid and str(sid) in self.blacklist_ids:
                continue
            if sname in self.blacklist_names:
                continue
            filtered.append(item)
        return filtered

    def _apply_models_filter(self, items, config):
        models = config.get("models", [])
        if not models:
            return items

        # 内存标识标准化函数
        def _normalize_memory_token(token):
            t = token.upper().replace(' ', '')
            # 统一 GB -> G
            t = t.replace('GB', 'G')
            # 去掉可能的后缀“内存”、“运存”
            t = re.sub(r'(内存|运存)$', '', t)
            return t

        # 内存/存储关键词匹配正则（保持原有逻辑，但后续会标准化）
        memory_pattern = re.compile(
            r'(\d{1,2}\s*(?:GB|G)\s*(?:内存|运存)?)|(DDR\d)',
            re.IGNORECASE
        )

        filtered = []
        for item in items:
            title = item.get("title", "")
            price_str = item.get("price", "")
            try:
                price = float(re.sub(r'[^\d.]', '', price_str))
            except:
                continue

            # 提取商品标题中的内存信息并标准化
            title_memory_tokens = set()
            for match in memory_pattern.finditer(title):
                token = match.group(0)
                normalized = _normalize_memory_token(token)
                title_memory_tokens.add(normalized)

            matched = False
            for model in models:
                keywords = model.get("keywords", [])
                min_p = model.get("min_price")
                max_p = model.get("max_price")
                memory_req = model.get("memory")

                # 价格过滤
                try:
                    min_p = float(min_p) if min_p is not None else None
                    max_p = float(max_p) if max_p is not None else None
                except:
                    min_p = None
                    max_p = None
                if min_p is not None and price < min_p:
                    continue
                if max_p is not None and price > max_p:
                    continue

                # 关键词过滤
                if not any(kw in title for kw in keywords):
                    continue

                # 内存过滤
                if memory_req and memory_req != "N/A":
                    # 标准化配置中的内存要求
                    req_tokens = set()
                    for part in re.split(r'[/,]', memory_req):
                        norm = _normalize_memory_token(part)
                        if norm:
                            req_tokens.add(norm)
                    # 只有当标题中有内存信息时才进行匹配；无内存信息则跳过
                    if title_memory_tokens:
                        if not any(req in title_memory_tokens for req in req_tokens):
                            continue  # 内存不匹配

                matched = True
                break

            if matched:
                filtered.append(item)

        return filtered

    def _apply_filters(self, items):
        config = None
        if self.current_config_name and self.current_config_name in self.filter_configs:
            config = self.filter_configs[self.current_config_name]

        if config and "models" in config:
            filtered = self._apply_models_filter(items, config)
            mode = self.filter_mode_var.get()
            if mode in ("blacklist", "both"):
                filtered = self._apply_blacklist_only(filtered)
            return filtered

        items = self._apply_model_filter(items)
        mode = self.filter_mode_var.get()
        if mode == "blacklist":
            return self._apply_blacklist_only(items)
        elif mode == "price":
            return self._apply_price_filter(items)
        elif mode == "both":
            return self._apply_price_filter(self._apply_blacklist_only(items))
        else:
            return items

    def refresh_display_with_filters(self):
        self.display_items = self._apply_filters(self.all_items)
        self.refresh_tree()
        mode_desc = {
            "blacklist": "黑名单过滤",
            "price": "价格过滤",
            "both": "价格+黑名单过滤"
        }.get(self.filter_mode_var.get(), "无过滤")
        self.info_var.set(f"当前显示 {len(self.display_items)} 个商品（模式：{mode_desc}）")
        logger.info(f"重新应用过滤，显示 {len(self.display_items)} 个商品")

    def _refresh_display_after_blacklist_change(self):
        if self.filter_mode_var.get() in ("blacklist", "both"):
            self.refresh_display_with_filters()

    def blacklist_selected_seller(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个或多个商品")
            return
        blocked_count = 0
        for tree_id in selection:
            values = self.tree.item(tree_id, "values")
            if not values or len(values) < 4:
                continue
            link = values[3]
            target_item = None
            for item in self.display_items:
                if item.get("link") == link:
                    target_item = item
                    break
            if target_item:
                sid = target_item.get("seller_id")
                sname = target_item.get("seller_name")
                if sid and str(sid).isdigit():
                    self.blacklist_ids.add(str(sid))
                    blocked_count += 1
                elif sid:
                    self.blacklist_names.add(str(sid))
                    blocked_count += 1
                elif sname and str(sname).strip():
                    self.blacklist_names.add(str(sname))
                    blocked_count += 1
        if blocked_count > 0:
            self.save_blacklist()
            self._refresh_display_after_blacklist_change()
            logger.info(f"批量拉黑 {blocked_count} 个卖家")
            messagebox.showinfo("成功", f"已拉黑 {blocked_count} 个卖家")
        else:
            messagebox.showinfo("提示", "所选商品没有可拉黑的卖家标识")

    def _manual_blacklist_dialog(self, link):
        dialog = tk.Toplevel(self.root)
        dialog.title("手动输入卖家标识")
        dialog.geometry("420x200")
        dialog.configure(bg=BG_DEEP_BLUE)
        tk.Label(dialog, text=f"商品链接: {link}", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack(pady=10)
        tk.Label(dialog, text="请输入卖家ID或昵称:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack()
        entry = tk.Entry(dialog, width=35, bg=BG_CONTAINER, fg=TEXT_WHITE, insertbackground=TEXT_WHITE)
        entry.pack(pady=5)
        entry.bind("<Return>", lambda e: confirm())

        def confirm():
            identifier = entry.get().strip()
            if identifier:
                if identifier.isdigit():
                    self._add_to_blacklist(identifier, is_id=True)
                else:
                    self._add_to_blacklist(identifier, is_id=False)
                dialog.destroy()
            else:
                messagebox.showwarning("提示", "卖家标识不能为空")

        tk.Button(dialog, text="确定", command=confirm, bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(pady=10)

    def _add_to_blacklist(self, identifier, is_id):
        if is_id:
            self.blacklist_ids.add(identifier)
        else:
            self.blacklist_names.add(identifier)
        self.save_blacklist()
        self._refresh_display_after_blacklist_change()
        logger.info(f"已拉黑{'ID' if is_id else '昵称'}: {identifier}")
        messagebox.showinfo("成功", f"已拉黑 {identifier}")

    def manage_blacklist_window(self):
        win = tk.Toplevel(self.root)
        win.title("管理黑名单")
        win.geometry("700x500")
        win.configure(bg=BG_DEEP_BLUE)

        main_frame = tk.Frame(win, bg=BG_DEEP_BLUE)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        id_frame = tk.LabelFrame(main_frame, text="卖家ID黑名单（纯数字）", bg=BG_DEEP_BLUE,
                                 fg=TEXT_WHITE, font=("微软雅黑", 10))
        id_frame.grid(row=0, column=0, sticky="nsew", padx=(0,5))
        id_list = tk.Listbox(id_frame, bg=BG_CONTAINER, fg=TEXT_WHITE, font=("Consolas", 10))
        id_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        id_scroll = ttk.Scrollbar(id_frame, orient=tk.VERTICAL, command=id_list.yview)
        id_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        id_list.config(yscrollcommand=id_scroll.set)
        for sid in sorted(self.blacklist_ids):
            id_list.insert(tk.END, sid)

        name_frame = tk.LabelFrame(main_frame, text="昵称黑名单", bg=BG_DEEP_BLUE,
                                   fg=TEXT_WHITE, font=("微软雅黑", 10))
        name_frame.grid(row=0, column=1, sticky="nsew", padx=(5,0))
        name_list = tk.Listbox(name_frame, bg=BG_CONTAINER, fg=TEXT_WHITE, font=("Consolas", 10))
        name_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        name_scroll = ttk.Scrollbar(name_frame, orient=tk.VERTICAL, command=name_list.yview)
        name_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        name_list.config(yscrollcommand=name_scroll.set)
        for name in sorted(self.blacklist_names):
            name_list.insert(tk.END, name)

        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        main_frame.rowconfigure(0, weight=1)

        op_frame = tk.Frame(win, bg=BG_DEEP_BLUE)
        op_frame.pack(fill=tk.X, padx=10, pady=10)
        tk.Label(op_frame, text="标识:", bg=BG_DEEP_BLUE, fg=TEXT_WHITE).pack(side=tk.LEFT)
        entry = tk.Entry(op_frame, width=25, bg=BG_CONTAINER, fg=TEXT_WHITE,
                         insertbackground=TEXT_WHITE, relief=tk.FLAT)
        entry.pack(side=tk.LEFT, padx=5)

        def add():
            identifier = entry.get().strip()
            if not identifier:
                return
            if identifier.isdigit():
                if identifier not in self.blacklist_ids:
                    self.blacklist_ids.add(identifier)
                    id_list.insert(tk.END, identifier)
                    self.save_blacklist()
                    logger.info(f"添加ID黑名单: {identifier}")
                    self._refresh_display_after_blacklist_change()
            else:
                if identifier not in self.blacklist_names:
                    self.blacklist_names.add(identifier)
                    name_list.insert(tk.END, identifier)
                    self.save_blacklist()
                    logger.info(f"添加昵称黑名单: {identifier}")
                    self._refresh_display_after_blacklist_change()
            entry.delete(0, tk.END)

        def remove_id():
            selection = id_list.curselection()
            if selection:
                identifier = id_list.get(selection[0])
                self.blacklist_ids.discard(identifier)
                id_list.delete(selection[0])
                self.save_blacklist()
                logger.info(f"移除ID黑名单: {identifier}")
                self._refresh_display_after_blacklist_change()

        def remove_name():
            selection = name_list.curselection()
            if selection:
                identifier = name_list.get(selection[0])
                self.blacklist_names.discard(identifier)
                name_list.delete(selection[0])
                self.save_blacklist()
                logger.info(f"移除昵称黑名单: {identifier}")
                self._refresh_display_after_blacklist_change()

        tk.Button(op_frame, text="添加", command=add, bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(op_frame, text="移除选中ID", command=remove_id, bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Button(op_frame, text="移除选中昵称", command=remove_name, bg=BTN_ORANGE, fg=TEXT_WHITE, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)

    # ---------- 采集与过滤（生命周期完整） ----------
    def start_search(self):
        keyword = self.keyword_entry.get().strip()
        if not keyword:
            messagebox.showwarning("提示", "请输入搜索关键词")
            return
        self.auto_load_config_for_keyword(keyword)
        try:
            start_page = int(self.start_page_spinbox.get())
            max_pages = int(self.pages_spinbox.get())
        except:
            start_page = 1
            max_pages = 10
        self.search_btn.config(state=tk.DISABLED)
        logger.info(f"开始采集，关键词: {keyword}, 起始页: {start_page}, 页数: {max_pages}（不自动过滤专业商家）")
        threading.Thread(target=self._search_thread, args=(keyword, start_page, max_pages), daemon=True).start()

    def _search_thread(self, keyword, start_page, max_pages):
        crawler = None
        try:
            crawler = GoofishCrawler()
            asyncio.run(self._run_crawler(crawler, keyword, start_page, max_pages))
        except Exception as e:
            logger.error(f"采集过程出错: {e}")
        finally:
            self.root.after(0, self._on_search_complete)
            self.root.after(0, lambda: self.search_btn.config(state=tk.NORMAL))

    async def _run_crawler(self, crawler, keyword, start_page, max_pages):
        try:
            await crawler.start(headless=True)
            items = await crawler.search(keyword, start_page, max_pages, check_professional=False)
            self.all_items = items
            self.display_items = self._apply_filters(items)
            self.last_keyword = keyword
            self.last_start_page = start_page
            self.last_max_pages = max_pages
            self._save_to_tsv(items)
        finally:
            await crawler.close()

    def _on_search_complete(self):
        self.refresh_tree()
        info = (f"关键词: {self.last_keyword} | 起始页: {self.last_start_page} | "
                f"页数: {self.last_max_pages} | 商品数: {len(self.all_items)} | "
                f"显示: {len(self.display_items)}")
        self.info_var.set(info)
        logger.info("搜索完成，结果已更新（未过滤专业商家）")

    def _filter_matched_items(self, items):
        self.filtering = True
        for widget in [self.search_btn, self.login_btn, self.copy_all_btn,
                       self.show_all_btn, self.edit_template_btn, self.web_ui_btn]:
            widget.config(state=tk.DISABLED)
        threading.Thread(target=self._filter_thread, args=(items,), daemon=True).start()

    def _filter_thread(self, items):
        crawler = None
        try:
            crawler = GoofishCrawler()
            asyncio.run(self._run_filter(crawler, items))
        except Exception as e:
            logger.error(f"过滤专业商家出错: {e}")
        finally:
            self.root.after(0, self._on_filter_complete)

    async def _run_filter(self, crawler, items):
        try:
            await crawler.start(headless=True)
            filtered = await crawler._filter_page(items, True)
            crawler.save_blacklist()
            self.display_items = self._apply_filters(filtered)
            self._save_to_tsv(self.display_items)
        finally:
            await crawler.close()

    def _on_filter_complete(self):
        self.filtering = False
        for widget in [self.search_btn, self.login_btn, self.copy_all_btn,
                       self.show_all_btn, self.edit_template_btn, self.web_ui_btn]:
            widget.config(state=tk.NORMAL)
        self.refresh_tree()
        self.info_var.set(f"AI筛选+专业商家过滤后保留 {len(self.display_items)} 个商品")
        logger.info("专业商家过滤完成")

    def _load_template(self):
        default_template = """请对以下闲鱼商品进行核查，判断是否存在价格异常、虚假描述或其他问题。

关键词: {{关键词}}
商品数量: {{商品数量}}

**重要：请在输出中保留商品前的编号（例如 #1、#2），以便程序自动匹配。**

商品列表：
{{商品数据列表}}"""
        if TEMPLATE_FILE.exists():
            try:
                with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
                    self.template_content = f.read()
                logger.info(f"已加载模板文件: {TEMPLATE_FILE.name}")
            except Exception as e:
                logger.error(f"读取模板文件失败: {e}")
                self.template_content = default_template
        else:
            logger.warning("提示词.txt 不存在，使用内置默认模板")
            self.template_content = default_template

    def _check_login_status(self):
        threading.Thread(target=self._check_login_thread, daemon=True).start()

    def _check_login_thread(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(USER_DATA_DIR), headless=True,
                    viewport=VIEWPORT, user_agent=USER_AGENT, args=BROWSER_ARGS)
                cookies = context.cookies()
                is_logged = any(c.get("name") in ("unb", "_m_h5_tk", "cookie2") for c in cookies)
                if is_logged:
                    logger.info("✅ 已检测到登录状态，可以开始采集。")
                else:
                    logger.warning("⚠️ 尚未登录闲鱼，请点击“登录闲鱼”按钮完成登录后再采集。")
                context.close()
        except Exception as e:
            logger.error(f"自动检测登录状态时出错: {e}")

    def login_goofish(self):
        self.login_btn.config(state=tk.DISABLED)
        logger.info("正在打开浏览器，请在窗口中完成登录...")
        threading.Thread(target=self._login_thread, daemon=True).start()

    def _login_thread(self):
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(USER_DATA_DIR), headless=False,
                    viewport=VIEWPORT, user_agent=USER_AGENT, args=BROWSER_ARGS)
                page = context.new_page()
                page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
                logger.info("请在弹出的浏览器中登录闲鱼，登录成功后关闭浏览器窗口即可。")
                try:
                    page.wait_for_event("close", timeout=0)
                except Exception as e:
                    logger.warning(f"等待浏览器关闭时出错: {e}")
                cookies = context.cookies()
                is_logged = any(c.get("name") in ("unb", "_m_h5_tk", "cookie2") for c in cookies)
                if is_logged:
                    logger.info("✅ 登录成功，状态已保存。")
                else:
                    logger.warning("⚠️ 可能未完成登录，请重新尝试。")
                try:
                    context.close()
                except:
                    pass
        except Exception as e:
            logger.error(f"登录过程出错: {e}")
        finally:
            self.root.after(0, lambda: self.login_btn.config(state=tk.NORMAL))

    def _save_to_tsv(self, items):
        if not items:
            return
        RESULT_DIR.mkdir(exist_ok=True)
        fieldnames = ["title", "price", "link", "seller_name", "seller_id"]
        with open(RESULT_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter="\t")
            writer.writeheader()
            for item in items:
                writer.writerow({
                    "title": item["title"],
                    "price": item.get("price", ""),
                    "link": item["link"],
                    "seller_name": item.get("seller_name", ""),
                    "seller_id": item.get("seller_id", "")
                })
        logger.info(f"数据已覆盖保存至 {RESULT_FILE}")

    def refresh_tree(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.display_items:
            title = item.get("title", "")
            if len(title) > 60:
                title = title[:60] + "..."
            self.tree.insert("", "end", values=(
                title,
                item.get("price", ""),
                item.get("seller_name", ""),
                item["link"]
            ))

    def open_selected_link(self, event=None):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选择一个商品")
            return
        values = self.tree.item(selection[0], "values")
        if values and len(values) >= 4:
            link = values[3]
            if link:
                webbrowser.open(link)
                logger.info(f"已在本地浏览器打开链接: {link}")

    def show_all_items(self):
        self.display_items = self._apply_filters(self.all_items)
        self.refresh_tree()
        mode_desc = {
            "blacklist": "黑名单过滤",
            "price": "价格过滤",
            "both": "价格+黑名单过滤"
        }.get(self.filter_mode_var.get(), "无过滤")
        logger.info(f"显示全部商品（模式：{mode_desc}）")
        self.info_var.set(f"显示全部 {len(self.display_items)} 个商品（模式：{mode_desc}）")

    def copy_all_data(self):
        if not self.display_items:
            messagebox.showwarning("提示", "没有数据可复制")
            return
        template = self.template_content
        items_text = ""
        for idx, item in enumerate(self.display_items, 1):
            items_text += f"#{idx}. 标题: {item['title']}\n   价格: {item.get('price', '')}\n"
            seller_name = item.get('seller_name', '')
            if seller_name:
                items_text += f"   卖家昵称: {seller_name}\n"
            items_text += f"   链接: {item['link']}\n\n"
        if "{{商品数据列表}}" in template:
            final_text = template.replace("{{商品数据列表}}", items_text)
            final_text = final_text.replace("{{关键词}}", self.last_keyword)
            final_text = final_text.replace("{{商品数量}}", str(len(self.display_items)))
        else:
            final_text = template + "\n\n" + items_text
        self.root.clipboard_clear()
        self.root.clipboard_append(final_text)
        self.root.update()
        logger.info("数据已复制到剪贴板")
        messagebox.showinfo("成功", "商品数据已复制，可直接粘贴到AI对话框进行核查。")

    def apply_ai_filter(self):
        ai_text = self.ai_text.get("1.0", tk.END).strip()
        if not ai_text:
            messagebox.showwarning("提示", "请先粘贴AI审核结果")
            return
        if not self.all_items:
            messagebox.showwarning("提示", "没有采集数据，无法筛选")
            return
        matched_indices = set()
        number_pattern = re.findall(r'#(\d+)', ai_text)
        for num_str in number_pattern:
            idx = int(num_str) - 1
            if 0 <= idx < len(self.all_items):
                matched_indices.add(idx)
        if not matched_indices:
            links_in_ai = re.findall(r'https?://[^\s]+', ai_text)
            for link in links_in_ai:
                for i, item in enumerate(self.all_items):
                    if extract_item_id(link) == extract_item_id(item['link']):
                        matched_indices.add(i)
                        break
        if not matched_indices:
            logger.warning("未检测到编号或链接，尝试标题关键词匹配...")
            lines = [l.strip() for l in ai_text.splitlines() if l.strip()]
            keywords = []
            for line in lines:
                if not line.startswith(('|', '-', '#', '=', '✅', '⚠️', '❌')):
                    kw = line[:12].strip()
                    if kw:
                        keywords.append(kw)
            for kw in keywords:
                for i, item in enumerate(self.all_items):
                    if kw and kw in item['title']:
                        matched_indices.add(i)
        if not matched_indices:
            logger.warning("AI结果中未找到可匹配的商品")
            messagebox.showwarning("筛选失败", "未找到匹配商品，请检查AI结果格式")
            return
        matched_items = [self.all_items[i] for i in sorted(matched_indices)]
        logger.info(f"AI筛选匹配到 {len(matched_items)} 个商品")
        if self.filter_professional_var.get():
            logger.info("复选框已勾选，开始对匹配商品进行专业商家过滤...")
            self._filter_matched_items(matched_items)
        else:
            self.display_items = self._apply_filters(matched_items)
            self.refresh_tree()
            mode_desc = {
                "blacklist": "黑名单过滤",
                "price": "价格过滤",
                "both": "价格+黑名单过滤"
            }.get(self.filter_mode_var.get(), "无过滤")
            self.info_var.set(f"AI筛选后保留 {len(self.display_items)} 个商品（模式：{mode_desc}）")
            logger.info("复选框未勾选，跳过专业商家过滤")

    def open_web_ui(self):
        try:
            import web_ui
            if self.web_server:
                web_ui.stop_server(self.web_server)
                self.web_server = None
            self.web_server = web_ui.start_web_server()
        except Exception as e:
            logger.error(f"启动网页界面失败: {e}")
            messagebox.showerror("错误", f"启动网页界面失败: {e}")

    def open_template_editor(self):
        editor = tk.Toplevel(self.root)
        editor.title("编辑提示词模板")
        editor.geometry("800x600")
        editor.configure(bg=BG_DEEP_BLUE)
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(0, weight=1)
        text = scrolledtext.ScrolledText(editor, bg=BG_CONTAINER, fg=TEXT_WHITE,
                                         insertbackground=TEXT_WHITE, relief=tk.FLAT)
        text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        text.insert("1.0", self.template_content)
        btn_frame = tk.Frame(editor, bg=BG_DEEP_BLUE)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 10))
        btn_frame.columnconfigure(0, weight=1)
        btn_frame.columnconfigure(1, weight=1)
        tk.Button(btn_frame, text="保存模板", command=lambda: self._save_template_from_editor(text, editor),
                  bg=BTN_GREEN, fg=TEXT_WHITE, relief=tk.FLAT).grid(row=0, column=0, padx=5, sticky="ew")
        tk.Button(btn_frame, text="取消", command=editor.destroy,
                  bg=BTN_BLUE, fg=TEXT_WHITE, relief=tk.FLAT).grid(row=0, column=1, padx=5, sticky="ew")

    def _save_template_from_editor(self, text_widget, editor_window):
        content = text_widget.get("1.0", tk.END).strip()
        self.template_content = content
        try:
            with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("模板已保存")
            messagebox.showinfo("成功", "模板已保存")
            editor_window.destroy()
        except Exception as e:
            logger.error(f"保存模板失败: {e}")