import sys
import os
import json
import asyncio
import threading
import random
import re
import time
from datetime import datetime

# Исправление для Python 3.10+ - создание event loop перед импортом pyrogram
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from pyrogram import Client
from pyrogram.errors import FloodWait, UserAlreadyParticipant, ChatWriteForbidden, ChannelPrivate, InviteRequestSent
from pyrogram.types import Message, InputMediaPhoto
from telethon import TelegramClient as TelethonClient
from telethon import functions, types
from telethon.errors.rpcerrorlist import RpcCallFailError

# ========== ГЛОБАЛЬНЫЕ НАСТРОЙКИ ==========
VERSION = "3.2"
DATA_DIR = "data"
TELEGRAM_SESSIONS_DIR = "telegram_sessions"  # ТОЛЬКО ДЛЯ ПАРСЕРА
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TELEGRAM_SESSIONS_DIR, exist_ok=True)

# Файлы для хранения данных
ACCOUNTS_FILE = os.path.join(DATA_DIR, "accounts.json")
PROXIES_FILE = os.path.join(DATA_DIR, "proxies.json")
PROJECTS_FILE = os.path.join(DATA_DIR, "projects.json")
DATABASES_FILE = os.path.join(DATA_DIR, "databases.json")
PARSED_USERS_FILE = os.path.join(DATA_DIR, "parsed_users.json")
TELEGRAM_ACCOUNTS_FILE = os.path.join(DATA_DIR, "telegram_accounts.json")

API_ID = 31972424
API_HASH = "1da171f9f44ece6830bbb013aff34677"

# ========== МОДЕЛИ ДАННЫХ ==========
class Account:
    def __init__(self, phone, name, session_path, is_valid=True, is_banned=False):
        self.phone = phone
        self.name = name
        self.session_path = session_path
        self.is_valid = is_valid
        self.is_banned = is_banned
        self.in_use = False
    
    def to_dict(self):
        return {"phone": self.phone, "name": self.name, "session_path": self.session_path,
                "is_valid": self.is_valid, "is_banned": self.is_banned, "in_use": self.in_use}
    
    @staticmethod
    def from_dict(data):
        acc = Account(data["phone"], data["name"], data["session_path"])
        acc.is_valid = data.get("is_valid", True)
        acc.is_banned = data.get("is_banned", False)
        acc.in_use = data.get("in_use", False)
        return acc

class TelegramAccount:
    def __init__(self, phone, name, session_path, is_valid=True, is_banned=False):
        self.phone = phone
        self.name = name
        self.session_path = session_path
        self.is_valid = is_valid
        self.is_banned = is_banned
    
    def to_dict(self):
        return {"phone": self.phone, "name": self.name, "session_path": self.session_path,
                "is_valid": self.is_valid, "is_banned": self.is_banned}
    
    @staticmethod
    def from_dict(data):
        acc = TelegramAccount(data["phone"], data["name"], data["session_path"], data.get("is_valid", True))
        acc.is_banned = data.get("is_banned", False)
        return acc

class Proxy:
    def __init__(self, proxy_string, is_working=True):
        self.proxy_string = proxy_string
        self.is_working = is_working
        self.in_use = False
        self.speed_ms = -1
    
    def to_dict(self):
        return {"proxy_string": self.proxy_string, "is_working": self.is_working, "in_use": self.in_use, "speed_ms": self.speed_ms}
    
    @staticmethod
    def from_dict(data):
        p = Proxy(data["proxy_string"])
        p.is_working = data.get("is_working", True)
        p.in_use = data.get("in_use", False)
        p.speed_ms = data.get("speed_ms", -1)
        return p

class Project:
    def __init__(self, name, account_phone, proxy_string, channels_list, comments_list, reply_text, 
                 delay_min=15, delay_max=30, subscribe_delay_min=5, subscribe_delay_max=10, 
                 auto_subscribe=True, auto_comment=True, auto_join_chat=True, auto_reply=True,
                 comment_mode="text", photos_folder="",
                 pause_after_count=0, pause_duration=60):
        self.name = name
        self.account_phone = account_phone
        self.proxy_string = proxy_string
        self.channels = channels_list
        self.comments = comments_list
        self.reply_text = reply_text
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.subscribe_delay_min = subscribe_delay_min
        self.subscribe_delay_max = subscribe_delay_max
        self.auto_subscribe = auto_subscribe
        self.auto_comment = auto_comment
        self.auto_join_chat = auto_join_chat
        self.auto_reply = auto_reply
        self.comment_mode = comment_mode
        self.photos_folder = photos_folder
        self.pause_after_count = pause_after_count
        self.pause_duration = pause_duration
        self.photos_list = []
        self.is_running = False
        self.thread = None
        self.subscribed_channels = []
        self.joined_chats = []
        self.skipped_channels = []
        self.chat_ids = {}
        self.last_post_ids = {}
        self.stats = {"comments": 0, "errors": 0, "replies": 0, "subscribes": 0, "chats_joined": 0, "skipped": 0, "last_action": ""}
        
        if self.photos_folder and os.path.exists(self.photos_folder):
            self.photos_list = [f for f in os.listdir(self.photos_folder) 
                               if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
    
    def to_dict(self):
        return {"name": self.name, "account_phone": self.account_phone, "proxy_string": self.proxy_string,
                "channels": self.channels, "comments": self.comments, "reply_text": self.reply_text,
                "delay_min": self.delay_min, "delay_max": self.delay_max,
                "subscribe_delay_min": self.subscribe_delay_min, "subscribe_delay_max": self.subscribe_delay_max,
                "auto_subscribe": self.auto_subscribe, "auto_comment": self.auto_comment,
                "auto_join_chat": self.auto_join_chat, "auto_reply": self.auto_reply,
                "comment_mode": self.comment_mode, "photos_folder": self.photos_folder,
                "pause_after_count": self.pause_after_count, "pause_duration": self.pause_duration,
                "is_running": self.is_running, "stats": self.stats,
                "chat_ids": self.chat_ids, "last_post_ids": self.last_post_ids}
    
    @staticmethod
    def from_dict(data):
        p = Project(data["name"], data["account_phone"], data["proxy_string"], data["channels"],
                    data["comments"], data["reply_text"], data.get("delay_min", 15),
                    data.get("delay_max", 30), data.get("subscribe_delay_min", 5),
                    data.get("subscribe_delay_max", 10), data.get("auto_subscribe", True),
                    data.get("auto_comment", True), data.get("auto_join_chat", True),
                    data.get("auto_reply", True),
                    data.get("comment_mode", "text"), data.get("photos_folder", ""),
                    data.get("pause_after_count", 0), data.get("pause_duration", 60))
        p.is_running = data.get("is_running", False)
        p.stats = data.get("stats", {"comments": 0, "errors": 0, "replies": 0, "subscribes": 0, "chats_joined": 0, "skipped": 0, "last_action": ""})
        p.chat_ids = data.get("chat_ids", {})
        p.last_post_ids = data.get("last_post_ids", {})
        if p.photos_folder and os.path.exists(p.photos_folder):
            p.photos_list = [f for f in os.listdir(p.photos_folder) 
                           if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
        return p

# ========== ДИАЛОГИ ==========
class TelegramPhoneDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавление аккаунта Telegram")
        self.setModal(True)
        self.setFixedSize(400, 200)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; font-size: 12px; }
            QLineEdit { background-color: #181825; border: 1px solid #313244; border-radius: 6px; padding: 8px; color: #cdd6f4; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("📱 Номер телефона (в международном формате):"))
        layout.addWidget(QLabel("Пример: +79123456789"))
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+79123456789")
        layout.addWidget(self.phone_input)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("Далее →")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def get_phone(self):
        return self.phone_input.text().strip()

class TelegramCodeDialog(QDialog):
    def __init__(self, phone, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подтверждение входа")
        self.setModal(True)
        self.setFixedSize(400, 250)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QLineEdit { background-color: #181825; border: 1px solid #313244; border-radius: 6px; padding: 8px; color: #cdd6f4; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"📱 На номер {phone} отправлен код подтверждения"))
        layout.addWidget(QLabel("Введите код из Telegram:"))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Введите код из 5 цифр")
        layout.addWidget(self.code_input)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("✅ Подтвердить")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("❌ Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def get_code(self):
        return self.code_input.text().strip()

class TelegramPasswordDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Двухфакторная аутентификация")
        self.setModal(True)
        self.setFixedSize(400, 200)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QLineEdit { background-color: #181825; border: 1px solid #313244; border-radius: 6px; padding: 8px; color: #cdd6f4; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("🔐 Включена двухфакторная аутентификация"))
        layout.addWidget(QLabel("Введите пароль:"))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Введите пароль 2FA")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("✅ Войти")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("❌ Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def get_password(self):
        return self.password_input.text().strip()

class PhoneInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Добавление аккаунта")
        self.setModal(True)
        self.setFixedSize(400, 200)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; font-size: 12px; }
            QLineEdit { background-color: #181825; border: 1px solid #313244; border-radius: 6px; padding: 8px; color: #cdd6f4; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("📱 Номер телефона (в международном формате):"))
        layout.addWidget(QLabel("Пример: +79123456789"))
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("+79123456789")
        layout.addWidget(self.phone_input)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("Далее →")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def get_phone(self):
        return self.phone_input.text().strip()

class CodeInputDialog(QDialog):
    def __init__(self, phone, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Подтверждение входа")
        self.setModal(True)
        self.setFixedSize(400, 250)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QLineEdit { background-color: #181825; border: 1px solid #313244; border-radius: 6px; padding: 8px; color: #cdd6f4; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"📱 На номер {phone} отправлен код подтверждения"))
        layout.addWidget(QLabel("Введите код из Telegram:"))
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Введите код из 5 цифр")
        layout.addWidget(self.code_input)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("✅ Подтвердить")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("❌ Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def get_code(self):
        return self.code_input.text().strip()

class PasswordInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Двухфакторная аутентификация")
        self.setModal(True)
        self.setFixedSize(400, 200)
        self.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QLineEdit { background-color: #181825; border: 1px solid #313244; border-radius: 6px; padding: 8px; color: #cdd6f4; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        layout = QVBoxLayout()
        layout.addWidget(QLabel("🔐 Включена двухфакторная аутентификация"))
        layout.addWidget(QLabel("Введите пароль:"))
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Введите пароль 2FA")
        self.password_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.password_input)
        layout.addStretch()
        btn_layout = QHBoxLayout()
        self.ok_btn = QPushButton("✅ Войти")
        self.ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("❌ Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)
    
    def get_password(self):
        return self.password_input.text().strip()

# ========== ГЛАВНОЕ ОКНО ==========
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"TG AutoCommenter Pro v{VERSION}")
        self.setGeometry(100, 100, 1300, 800)
        
        self.accounts = []
        self.proxies = []
        self.projects = []
        self.databases = []
        self.parsed_users = []
        self.telegram_accounts = []
        
        self.load_all_data()
        self.setup_ui()
        
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.update_stats_display)
        self.stats_timer.start(1000)
    
    def setup_ui(self):
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        
        self.dashboard_tab = DashboardTab(self)
        self.accounts_tab = AccountsTab(self)
        self.proxies_tab = ProxiesTab(self)
        self.projects_tab = ProjectsTab(self)
        self.similar_parser_tab = SimilarParserTab(self)
        self.databases_tab = DatabasesTab(self)
        
        self.tabs.addTab(self.dashboard_tab, "📊 Дашборд")
        self.tabs.addTab(self.accounts_tab, "📱 Аккаунты")
        self.tabs.addTab(self.proxies_tab, "🔒 Прокси")
        self.tabs.addTab(self.projects_tab, "⚡ Потоки")
        self.tabs.addTab(self.similar_parser_tab, "🔍 Similar Parser")
        self.tabs.addTab(self.databases_tab, "📊 Базы")
        
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.update_status()
    
    def update_status(self):
        running = sum(1 for p in self.projects if p.is_running)
        total_comments = sum(p.stats["comments"] for p in self.projects)
        total_subscribes = sum(p.stats["subscribes"] for p in self.projects)
        total_chats = sum(p.stats["chats_joined"] for p in self.projects)
        total_replies = sum(p.stats["replies"] for p in self.projects)
        self.statusBar.showMessage(f"Аккаунтов: {len(self.accounts)} | Прокси: {len(self.proxies)} | Проектов: {len(self.projects)} | Активных: {running} | Комментариев: {total_comments} | Подписок: {total_subscribes} | Чатов: {total_chats} | Ответов в ЛС: {total_replies}")
    
    def update_stats_display(self):
        self.update_status()
        if hasattr(self, 'dashboard_tab'):
            self.dashboard_tab.refresh_stats()
    
    def load_all_data(self):
        self.load_accounts()
        self.load_proxies()
        self.load_projects()
        self.load_databases()
        self.load_parsed_users()
        self.load_telegram_accounts()
    
    def load_accounts(self):
        if os.path.exists(ACCOUNTS_FILE):
            with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                self.accounts = [Account.from_dict(acc) for acc in json.load(f)]
    
    def save_accounts(self):
        with open(ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump([acc.to_dict() for acc in self.accounts], f, ensure_ascii=False, indent=2)
        self.update_status()
    
    def load_telegram_accounts(self):
        if os.path.exists(TELEGRAM_ACCOUNTS_FILE):
            with open(TELEGRAM_ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                self.telegram_accounts = [TelegramAccount.from_dict(acc) for acc in json.load(f)]
    
    def save_telegram_accounts(self):
        with open(TELEGRAM_ACCOUNTS_FILE, 'w', encoding='utf-8') as f:
            json.dump([acc.to_dict() for acc in self.telegram_accounts], f, ensure_ascii=False, indent=2)
    
    def load_proxies(self):
        if os.path.exists(PROXIES_FILE):
            with open(PROXIES_FILE, 'r', encoding='utf-8') as f:
                self.proxies = [Proxy.from_dict(p) for p in json.load(f)]
    
    def save_proxies(self):
        with open(PROXIES_FILE, 'w', encoding='utf-8') as f:
            json.dump([p.to_dict() for p in self.proxies], f, ensure_ascii=False, indent=2)
        self.update_status()
    
    def load_projects(self):
        if os.path.exists(PROJECTS_FILE):
            with open(PROJECTS_FILE, 'r', encoding='utf-8') as f:
                self.projects = [Project.from_dict(p) for p in json.load(f)]
    
    def save_projects(self):
        with open(PROJECTS_FILE, 'w', encoding='utf-8') as f:
            json.dump([p.to_dict() for p in self.projects], f, ensure_ascii=False, indent=2)
        self.update_status()
    
    def load_databases(self):
        if os.path.exists(DATABASES_FILE):
            with open(DATABASES_FILE, 'r', encoding='utf-8') as f:
                self.databases = json.load(f)
    
    def save_databases(self):
        with open(DATABASES_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.databases, f, ensure_ascii=False, indent=2)
    
    def load_parsed_users(self):
        if os.path.exists(PARSED_USERS_FILE):
            with open(PARSED_USERS_FILE, 'r', encoding='utf-8') as f:
                self.parsed_users = json.load(f)

# ========== ДАШБОРД ==========
class DashboardTab(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setup_ui()
    
    def setup_ui(self):
        layout = QVBoxLayout()
        stats_layout = QHBoxLayout()
        
        self.total_accounts_card = self.create_stat_card("📱 Аккаунты", "0", "#2196F3")
        self.total_proxies_card = self.create_stat_card("🔒 Прокси", "0", "#FF9800")
        self.total_projects_card = self.create_stat_card("⚡ Проекты", "0", "#9C27B0")
        self.active_projects_card = self.create_stat_card("🟢 Активные", "0", "#4CAF50")
        
        stats_layout.addWidget(self.total_accounts_card)
        stats_layout.addWidget(self.total_proxies_card)
        stats_layout.addWidget(self.total_projects_card)
        stats_layout.addWidget(self.active_projects_card)
        layout.addLayout(stats_layout)
        
        total_stats_layout = QHBoxLayout()
        self.total_comments_card = self.create_stat_card("💬 Комментариев", "0", "#E91E63")
        self.total_errors_card = self.create_stat_card("❌ Ошибок", "0", "#F44336")
        self.total_subscribes_card = self.create_stat_card("📢 Подписок", "0", "#00BCD4")
        self.total_chats_card = self.create_stat_card("💬 Чатов", "0", "#4CAF50")
        self.total_replies_card = self.create_stat_card("✉️ Ответов в ЛС", "0", "#FF9800")
        
        total_stats_layout.addWidget(self.total_comments_card)
        total_stats_layout.addWidget(self.total_errors_card)
        total_stats_layout.addWidget(self.total_subscribes_card)
        total_stats_layout.addWidget(self.total_chats_card)
        total_stats_layout.addWidget(self.total_replies_card)
        layout.addLayout(total_stats_layout)
        
        layout.addWidget(QLabel("📊 Активные потоки:"))
        self.projects_table = QTableWidget()
        self.projects_table.setColumnCount(8)
        self.projects_table.setHorizontalHeaderLabels(["Проект", "Аккаунт", "Комментарии", "Подписки", "Чаты", "Ответы в ЛС", "Ошибки", "Последнее действие"])
        layout.addWidget(self.projects_table)
        
        self.setLayout(layout)
        self.refresh_stats()
    
    def create_stat_card(self, title, value, color):
        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background-color: {color}; border-radius: 10px; padding: 15px; }} QLabel {{ color: white; }}")
        card_layout = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 14px;")
        value_label = QLabel(value)
        value_label.setStyleSheet("font-size: 28px; font-weight: bold;")
        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        card.setLayout(card_layout)
        card.value_label = value_label
        return card
    
    def refresh_stats(self):
        self.total_accounts_card.value_label.setText(str(len(self.main.accounts)))
        self.total_proxies_card.value_label.setText(str(len(self.main.proxies)))
        self.total_projects_card.value_label.setText(str(len(self.main.projects)))
        active = sum(1 for p in self.main.projects if p.is_running)
        self.active_projects_card.value_label.setText(str(active))
        
        total_comments = sum(p.stats["comments"] for p in self.main.projects)
        total_errors = sum(p.stats["errors"] for p in self.main.projects)
        total_subscribes = sum(p.stats["subscribes"] for p in self.main.projects)
        total_chats = sum(p.stats["chats_joined"] for p in self.main.projects)
        total_replies = sum(p.stats["replies"] for p in self.main.projects)
        
        self.total_comments_card.value_label.setText(str(total_comments))
        self.total_errors_card.value_label.setText(str(total_errors))
        self.total_subscribes_card.value_label.setText(str(total_subscribes))
        self.total_chats_card.value_label.setText(str(total_chats))
        self.total_replies_card.value_label.setText(str(total_replies))
        
        self.projects_table.setRowCount(len(self.main.projects))
        for i, p in enumerate(self.main.projects):
            self.projects_table.setItem(i, 0, QTableWidgetItem(p.name))
            self.projects_table.setItem(i, 1, QTableWidgetItem(p.account_phone))
            self.projects_table.setItem(i, 2, QTableWidgetItem(str(p.stats["comments"])))
            self.projects_table.setItem(i, 3, QTableWidgetItem(str(p.stats["subscribes"])))
            self.projects_table.setItem(i, 4, QTableWidgetItem(str(p.stats["chats_joined"])))
            self.projects_table.setItem(i, 5, QTableWidgetItem(str(p.stats["replies"])))
            self.projects_table.setItem(i, 6, QTableWidgetItem(str(p.stats["errors"])))
            self.projects_table.setItem(i, 7, QTableWidgetItem(p.stats["last_action"][:50]))

# ========== ВКЛАДКА АККАУНТОВ ==========
class AccountsTab(QWidget):
    refresh_signal = pyqtSignal()
    error_signal = pyqtSignal(str)
    success_signal = pyqtSignal()
    password_signal = pyqtSignal()
    code_signal = pyqtSignal()
    
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.current_phone = None
        self.current_client = None
        self.current_phone_code_hash = None
        self.current_loop = None
        self.setup_ui()
        
        self.refresh_signal.connect(self.refresh_table)
        self.error_signal.connect(self.show_error)
        self.success_signal.connect(self.show_success)
        self.password_signal.connect(self.request_password)
        self.code_signal.connect(self.show_code_dialog)
    
    def setup_ui(self):
        layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("➕ Добавить аккаунт")
        self.add_btn.clicked.connect(self.add_account)
        self.check_all_btn = QPushButton("🔍 Проверить все")
        self.check_all_btn.clicked.connect(self.check_all_accounts)
        self.remove_btn = QPushButton("🗑 Удалить выбранные")
        self.remove_btn.clicked.connect(self.remove_selected)
        
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.check_all_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Телефон", "Имя", "Валид", "Бан", "Используется"])
        layout.addWidget(self.table)
        
        self.setLayout(layout)
        self.refresh_table()
    
    @pyqtSlot()
    def refresh_table(self):
        self.table.setRowCount(len(self.main.accounts))
        for i, acc in enumerate(self.main.accounts):
            self.table.setItem(i, 0, QTableWidgetItem(acc.phone))
            self.table.setItem(i, 1, QTableWidgetItem(acc.name))
            self.table.setItem(i, 2, QTableWidgetItem("✅" if acc.is_valid else "❌"))
            self.table.setItem(i, 3, QTableWidgetItem("⚠️" if acc.is_banned else "✅"))
            self.table.setItem(i, 4, QTableWidgetItem("🔴" if acc.in_use else "🟢"))
    
    def add_account(self):
        phone_dialog = PhoneInputDialog(self)
        if phone_dialog.exec_():
            phone = phone_dialog.get_phone()
            if phone:
                self.current_phone = phone
                self.add_btn.setEnabled(False)
                self.add_btn.setText("⏳ Отправка кода...")
                threading.Thread(target=self.send_code_thread, args=(phone,), daemon=True).start()
    
    def send_code_thread(self, phone):
        try:
            session_path = os.path.join(DATA_DIR, f"session_{phone}")
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def send_code():
                client = Client(session_path, api_id=API_ID, api_hash=API_HASH)
                await client.connect()
                sent_code = await client.send_code(phone)
                return client, sent_code.phone_code_hash
            
            client, phone_code_hash = loop.run_until_complete(send_code())
            self.current_client = client
            self.current_phone_code_hash = phone_code_hash
            self.current_loop = loop
            self.code_signal.emit()
            
        except Exception as e:
            self.error_signal.emit(str(e))
    
    @pyqtSlot()
    def show_code_dialog(self):
        self.add_btn.setText("⏳ Ожидание кода...")
        code_dialog = CodeInputDialog(self.current_phone, self)
        if code_dialog.exec_():
            code = code_dialog.get_code()
            if code:
                threading.Thread(target=self.sign_in_thread, args=(code,), daemon=True).start()
            else:
                self.error_signal.emit("Код не введен")
        else:
            self.error_signal.emit("Авторизация отменена")
    
    def sign_in_thread(self, code):
        try:
            loop = self.current_loop if self.current_loop else asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def sign_in():
                await self.current_client.sign_in(
                    phone_number=self.current_phone,
                    phone_code_hash=self.current_phone_code_hash,
                    phone_code=code
                )
                me = await self.current_client.get_me()
                await self.current_client.disconnect()
                return me
            
            me = loop.run_until_complete(sign_in())
            session_path = os.path.join(DATA_DIR, f"session_{self.current_phone}")
            acc = Account(self.current_phone, me.first_name or me.username or self.current_phone, session_path, True, False)
            self.main.accounts.append(acc)
            self.main.save_accounts()
            self.refresh_signal.emit()
            self.success_signal.emit()
            loop.close()
            
        except Exception as e:
            error_str = str(e)
            if "password" in error_str.lower():
                self.password_signal.emit()
            else:
                self.error_signal.emit(error_str)
    
    @pyqtSlot()
    def request_password(self):
        self.add_btn.setText("⏳ Требуется пароль 2FA...")
        password_dialog = PasswordInputDialog(self)
        if password_dialog.exec_():
            password = password_dialog.get_password()
            if password:
                threading.Thread(target=self.check_password_thread, args=(password,), daemon=True).start()
            else:
                self.error_signal.emit("Пароль не введен")
        else:
            self.error_signal.emit("Авторизация отменена")
    
    def check_password_thread(self, password):
        try:
            loop = self.current_loop if self.current_loop else asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def check_password():
                await self.current_client.check_password(password)
                me = await self.current_client.get_me()
                await self.current_client.disconnect()
                return me
            
            me = loop.run_until_complete(check_password())
            session_path = os.path.join(DATA_DIR, f"session_{self.current_phone}")
            acc = Account(self.current_phone, me.first_name or me.username or self.current_phone, session_path, True, False)
            self.main.accounts.append(acc)
            self.main.save_accounts()
            self.refresh_signal.emit()
            self.success_signal.emit()
            loop.close()
            
        except Exception as e:
            self.error_signal.emit(str(e))
    
    @pyqtSlot()
    def show_success(self):
        self.add_btn.setEnabled(True)
        self.add_btn.setText("➕ Добавить аккаунт")
        QMessageBox.information(self, "Успех", "✅ Аккаунт успешно добавлен!")
        self.current_client = None
    
    @pyqtSlot(str)
    def show_error(self, msg):
        self.add_btn.setEnabled(True)
        self.add_btn.setText("➕ Добавить аккаунт")
        if self.current_client:
            self.current_client = None
        QMessageBox.critical(self, "Ошибка", f"❌ {msg}")
    
    def check_all_accounts(self):
        if not self.main.accounts:
            QMessageBox.warning(self, "Ошибка", "Нет аккаунтов для проверки!")
            return
        self.check_all_btn.setEnabled(False)
        self.check_all_btn.setText("⏳ Проверка...")
        def check_all_thread():
            for acc in self.main.accounts:
                self.check_account(acc)
            self.main.save_accounts()
            self.refresh_signal.emit()
            QMetaObject.invokeMethod(self, "on_check_all_finished", Qt.QueuedConnection)
        threading.Thread(target=check_all_thread, daemon=True).start()

    @pyqtSlot()
    def on_check_all_finished(self):
        self.check_all_btn.setEnabled(True)
        self.check_all_btn.setText("🔍 Проверить все")
        valid_count = sum(1 for a in self.main.accounts if a.is_valid)
        banned_count = sum(1 for a in self.main.accounts if a.is_banned)
        QMessageBox.information(self, "Проверка завершена",
            f"✅ Валидных: {valid_count}\n"
            f"⚠️ Спам-блок: {banned_count}\n"
            f"❌ Невалидных: {len(self.main.accounts) - valid_count}")
    
    def check_account(self, account):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def check():
                async with Client(account.session_path, api_id=API_ID, api_hash=API_HASH) as client:
                    me = await client.get_me()
                    if me:
                        account.is_valid = True
                        account.name = me.first_name or me.username or account.phone
                    else:
                        account.is_valid = False
                        account.is_banned = True
                        return

                    try:
                        await client.send_message("SpamBot", "/start")
                        await asyncio.sleep(3)
                        spam_response = ""
                        async for msg in client.get_chat_history("SpamBot", limit=1):
                            spam_response = (msg.text or "").lower()
                            break

                        spam_keywords = ["limited", "restrict", "spam", "нарушен", "ограничен", "спам"]
                        free_keywords = ["free", "no limits", "свободен", "нет ограничений", "good news", "не ограничен"]

                        is_spam_blocked = False
                        for kw in free_keywords:
                            if kw in spam_response:
                                is_spam_blocked = False
                                break
                        else:
                            for kw in spam_keywords:
                                if kw in spam_response:
                                    is_spam_blocked = True
                                    break

                        account.is_banned = is_spam_blocked

                    except Exception:
                        account.is_banned = False

            loop.run_until_complete(check())
            loop.close()
            self.main.save_accounts()
            self.refresh_signal.emit()

        except Exception as e:
            error_str = str(e).lower()
            account.is_valid = False
            if "deactivated" in error_str or "deleted" in error_str:
                account.is_banned = True
            elif "auth" in error_str:
                account.is_banned = False
            else:
                account.is_banned = True
            self.main.save_accounts()
            self.refresh_signal.emit()
    
    def remove_selected(self):
        selected = self.table.selectedItems()
        if selected:
            rows = set(item.row() for item in selected)
            if QMessageBox.question(self, "Удаление", f"Удалить {len(rows)} аккаунт(ов)?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                for row in sorted(rows, reverse=True):
                    if row < len(self.main.accounts):
                        self.main.accounts.pop(row)
                self.main.save_accounts()
                self.refresh_signal.emit()

# ========== ВКЛАДКА ПРОКСИ ==========
class ProxiesTab(QWidget):
    refresh_signal = pyqtSignal()
    
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setup_ui()
        self.refresh_signal.connect(self.refresh_table)
    
    def setup_ui(self):
        layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("➕ Добавить прокси")
        self.add_btn.clicked.connect(self.add_proxy)
        self.add_file_btn = QPushButton("📁 Из файла")
        self.add_file_btn.clicked.connect(self.add_from_file)
        self.check_btn = QPushButton("🔍 Проверить все")
        self.check_btn.clicked.connect(self.check_all_proxies)
        self.check_single_btn = QPushButton("🔍 Проверить выбранный")
        self.check_single_btn.clicked.connect(self.check_selected_proxy)
        self.remove_btn = QPushButton("🗑 Удалить")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.remove_dead_btn = QPushButton("🗑 Удалить нерабочие")
        self.remove_dead_btn.clicked.connect(self.remove_dead_proxies)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.add_file_btn)
        btn_layout.addWidget(self.check_btn)
        btn_layout.addWidget(self.check_single_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addWidget(self.remove_dead_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Прокси", "Статус", "Скорость", "Используется"])
        layout.addWidget(self.table)
        
        self.setLayout(layout)
        self.refresh_table()
    
    @pyqtSlot()
    def refresh_table(self):
        self.table.setRowCount(len(self.main.proxies))
        for i, p in enumerate(self.main.proxies):
            self.table.setItem(i, 0, QTableWidgetItem(p.proxy_string))
            self.table.setItem(i, 1, QTableWidgetItem("✅ Работает" if p.is_working else "❌ Не работает"))
            if p.speed_ms >= 0:
                if p.speed_ms < 500:
                    speed_text = f"🟢 {p.speed_ms} мс"
                elif p.speed_ms < 2000:
                    speed_text = f"🟡 {p.speed_ms} мс"
                else:
                    speed_text = f"🔴 {p.speed_ms} мс"
            else:
                speed_text = "— не проверено"
            self.table.setItem(i, 2, QTableWidgetItem(speed_text))
            self.table.setItem(i, 3, QTableWidgetItem("🔴" if p.in_use else "🟢"))
        self.table.resizeColumnsToContents()
    
    def validate_proxy(self, proxy_string):
        pattern = r'^(socks5|http|https)://(([^:]+):([^@]+)@)?([a-zA-Z0-9\.\-]+):(\d+)$'
        match = re.match(pattern, proxy_string)
        if not match:
            return False, "Неверный формат!\nПравильные форматы:\nhttp://user:pass@host:port\nsocks5://host:port"
        port = int(match.group(6))
        if port < 1 or port > 65535:
            return False, "Порт должен быть от 1 до 65535"
        return True, "OK"
    
    def test_proxy_connection(self, proxy_string):
        """Quick socket-level check (port open)"""
        try:
            import socket
            match = re.match(r'^(socks5|http|https)://(([^:]+):([^@]+)@)?([^:]+):(\d+)$', proxy_string)
            if not match:
                return False, -1
            host = match.group(5)
            port = int(match.group(6))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            start_t = time.time()
            result = sock.connect_ex((host, port))
            elapsed = int((time.time() - start_t) * 1000)
            sock.close()
            if result == 0:
                return True, elapsed
            return False, -1
        except Exception:
            return False, -1

    def test_proxy_http(self, proxy_string):
        """Full HTTP test through proxy — checks real connectivity and measures speed"""
        try:
            import urllib.request
            import urllib.error

            match = re.match(r'^(socks5|http|https)://(([^:]+):([^@]+)@)?([^:]+):(\d+)$', proxy_string)
            if not match:
                return False, -1

            proxy_type = match.group(1)

            if proxy_type in ('http', 'https'):
                proxy_handler = urllib.request.ProxyHandler({
                    'http': proxy_string,
                    'https': proxy_string
                })
                opener = urllib.request.build_opener(proxy_handler)
                start_t = time.time()
                resp = opener.open("http://httpbin.org/ip", timeout=10)
                elapsed = int((time.time() - start_t) * 1000)
                resp.read()
                resp.close()
                return True, elapsed
            else:
                return self.test_proxy_connection(proxy_string)

        except Exception:
            return self.test_proxy_connection(proxy_string)
    
    def add_proxy(self):
        text, ok = QInputDialog.getText(self, "Добавить прокси", "Введите прокси в формате:\nhttp://user:pass@host:port\nили\nsocks5://host:port")
        if ok and text:
            text = text.strip()
            is_valid, message = self.validate_proxy(text)
            if is_valid:
                exists = any(p.proxy_string == text for p in self.main.proxies)
                if exists:
                    QMessageBox.warning(self, "Ошибка", "Такой прокси уже существует!")
                    return
                self.add_btn.setEnabled(False)
                self.add_btn.setText("⏳ Проверка прокси...")
                def check_and_add():
                    is_working, speed = self.test_proxy_http(text)
                    proxy = Proxy(text, is_working)
                    proxy.speed_ms = speed
                    self.main.proxies.append(proxy)
                    self.main.save_proxies()
                    self.refresh_signal.emit()
                    QMetaObject.invokeMethod(self, "on_proxy_added", Qt.QueuedConnection,
                        Q_ARG(bool, is_working), Q_ARG(int, speed))
                threading.Thread(target=check_and_add, daemon=True).start()
            else:
                QMessageBox.warning(self, "Ошибка формата", message)

    @pyqtSlot(bool, int)
    def on_proxy_added(self, is_working, speed):
        self.add_btn.setEnabled(True)
        self.add_btn.setText("➕ Добавить прокси")
        if is_working:
            QMessageBox.information(self, "Успех",
                f"✅ Прокси добавлен и работает!\nСкорость: {speed} мс")
        else:
            QMessageBox.warning(self, "Предупреждение",
                "⚠️ Прокси добавлен, но НЕ прошёл проверку!\n"
                "Порт недоступен или прокси не работает.")
    
    def add_from_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл с прокси", "", "Text Files (*.txt)")
        if file_path:
            self.add_file_btn.setEnabled(False)
            self.add_file_btn.setText("⏳ Загрузка...")
            def add_thread():
                added = 0
                skipped = 0
                failed = 0
                with open(file_path, 'r', encoding='utf-8') as f:
                    lines = [l.strip() for l in f if l.strip()]
                for line in lines:
                    is_valid, _ = self.validate_proxy(line)
                    if not is_valid:
                        skipped += 1
                        continue
                    if any(p.proxy_string == line for p in self.main.proxies):
                        skipped += 1
                        continue
                    is_working, speed = self.test_proxy_http(line)
                    proxy = Proxy(line, is_working)
                    proxy.speed_ms = speed
                    self.main.proxies.append(proxy)
                    if is_working:
                        added += 1
                    else:
                        failed += 1
                self.main.save_proxies()
                self.refresh_signal.emit()
                QMetaObject.invokeMethod(self, "on_file_proxies_added", Qt.QueuedConnection,
                    Q_ARG(int, added), Q_ARG(int, failed), Q_ARG(int, skipped))
            threading.Thread(target=add_thread, daemon=True).start()

    @pyqtSlot(int, int, int)
    def on_file_proxies_added(self, added, failed, skipped):
        self.add_file_btn.setEnabled(True)
        self.add_file_btn.setText("📁 Из файла")
        QMessageBox.information(self, "Готово",
            f"✅ Рабочих добавлено: {added}\n"
            f"❌ Нерабочих добавлено: {failed}\n"
            f"⏭ Пропущено (дубли/невалидные): {skipped}")
    
    def check_all_proxies(self):
        if not self.main.proxies:
            QMessageBox.warning(self, "Ошибка", "Нет прокси для проверки!")
            return
        self.check_btn.setEnabled(False)
        self.check_btn.setText("⏳ Проверка...")
        def check_thread():
            working = 0
            dead = 0
            for proxy in self.main.proxies:
                is_working, speed = self.test_proxy_http(proxy.proxy_string)
                proxy.is_working = is_working
                proxy.speed_ms = speed
                if is_working:
                    working += 1
                else:
                    dead += 1
                self.refresh_signal.emit()
                time.sleep(0.3)
            self.main.save_proxies()
            self.refresh_signal.emit()
            QMetaObject.invokeMethod(self, "on_check_finished", Qt.QueuedConnection,
                Q_ARG(int, working), Q_ARG(int, dead))
        threading.Thread(target=check_thread, daemon=True).start()
    
    @pyqtSlot(int, int)
    def on_check_finished(self, working, dead):
        self.check_btn.setEnabled(True)
        self.check_btn.setText("🔍 Проверить все")
        QMessageBox.information(self, "Проверка завершена",
            f"✅ Рабочих: {working}\n❌ Нерабочих: {dead}")

    def check_selected_proxy(self):
        selected = self.table.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Выберите прокси для проверки!")
            return
        row = selected[0].row()
        if row >= len(self.main.proxies):
            return
        proxy = self.main.proxies[row]
        self.check_single_btn.setEnabled(False)
        self.check_single_btn.setText("⏳ Проверка...")
        def check_one():
            is_working, speed = self.test_proxy_http(proxy.proxy_string)
            proxy.is_working = is_working
            proxy.speed_ms = speed
            self.main.save_proxies()
            self.refresh_signal.emit()
            QMetaObject.invokeMethod(self, "on_single_check_finished", Qt.QueuedConnection,
                Q_ARG(str, proxy.proxy_string), Q_ARG(bool, is_working), Q_ARG(int, speed))
        threading.Thread(target=check_one, daemon=True).start()

    @pyqtSlot(str, bool, int)
    def on_single_check_finished(self, proxy_str, is_working, speed):
        self.check_single_btn.setEnabled(True)
        self.check_single_btn.setText("🔍 Проверить выбранный")
        if is_working:
            QMessageBox.information(self, "Результат",
                f"✅ Прокси работает!\n{proxy_str}\nСкорость: {speed} мс")
        else:
            QMessageBox.warning(self, "Результат",
                f"❌ Прокси НЕ работает!\n{proxy_str}")

    def remove_dead_proxies(self):
        dead = [p for p in self.main.proxies if not p.is_working]
        if not dead:
            QMessageBox.information(self, "Готово", "Нет нерабочих прокси для удаления!")
            return
        if QMessageBox.question(self, "Удаление", f"Удалить {len(dead)} нерабочих прокси?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.main.proxies = [p for p in self.main.proxies if p.is_working]
            self.main.save_proxies()
            self.refresh_table()
            QMessageBox.information(self, "Готово", f"Удалено {len(dead)} нерабочих прокси")
    
    def remove_selected(self):
        selected = self.table.selectedItems()
        if selected:
            rows = set(item.row() for item in selected)
            if QMessageBox.question(self, "Удаление", f"Удалить {len(rows)} прокси?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                for row in sorted(rows, reverse=True):
                    if row < len(self.main.proxies):
                        self.main.proxies.pop(row)
                self.main.save_proxies()
                self.refresh_table()

# ========== ВКЛАДКА ПОТОКОВ ==========
class ProjectsTab(QWidget):
    refresh_signal = pyqtSignal()
    
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setup_ui()
        self.refresh_signal.connect(self.refresh_table)
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        btn_layout = QHBoxLayout()
        self.create_btn = QPushButton("➕ Создать проект")
        self.create_btn.clicked.connect(self.create_project)
        self.stop_all_btn = QPushButton("⏹ Остановить все")
        self.stop_all_btn.clicked.connect(self.stop_all)
        btn_layout.addWidget(self.create_btn)
        btn_layout.addWidget(self.stop_all_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.table = QTableWidget()
        self.table.setColumnCount(10)
        self.table.setHorizontalHeaderLabels(["Название", "Аккаунт", "Режим", "Подписок", "Чатов", "Комментов", "Ответов в ЛС", "Статус", "Редактировать", "Действия"])
        layout.addWidget(self.table)
        
        self.setLayout(layout)
        self.refresh_table()
    
    @pyqtSlot()
    def refresh_table(self):
        self.table.setRowCount(len(self.main.projects))
        for i, p in enumerate(self.main.projects):
            self.table.setItem(i, 0, QTableWidgetItem(p.name))
            self.table.setItem(i, 1, QTableWidgetItem(p.account_phone))
            mode_text = "📷 Фото" if p.comment_mode == "photo" else "📝 Текст"
            self.table.setItem(i, 2, QTableWidgetItem(mode_text))
            self.table.setItem(i, 3, QTableWidgetItem(str(p.stats["subscribes"])))
            self.table.setItem(i, 4, QTableWidgetItem(str(p.stats["chats_joined"])))
            self.table.setItem(i, 5, QTableWidgetItem(str(p.stats["comments"])))
            self.table.setItem(i, 6, QTableWidgetItem(str(p.stats["replies"])))
            self.table.setItem(i, 7, QTableWidgetItem("🟢 RUN" if p.is_running else "🔴 STOP"))
            
            edit_btn = QPushButton("✏️ Ред.")
            edit_btn.setStyleSheet("background-color: #FF9800;")
            edit_btn.clicked.connect(lambda checked, idx=i: self.edit_project(idx))
            
            widget = QWidget()
            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.addWidget(edit_btn)
            
            if p.is_running:
                stop_btn = QPushButton("⏹ Стоп")
                stop_btn.clicked.connect(lambda checked, idx=i: self.stop_project(idx))
                btn_layout.addWidget(stop_btn)
            else:
                start_btn = QPushButton("▶ Старт")
                start_btn.clicked.connect(lambda checked, idx=i: self.start_project(idx))
                btn_layout.addWidget(start_btn)
            
            delete_btn = QPushButton("🗑 Удалить")
            delete_btn.clicked.connect(lambda checked, idx=i: self.delete_project(idx))
            btn_layout.addWidget(delete_btn)
            
            widget.setLayout(btn_layout)
            self.table.setCellWidget(i, 8, edit_btn)
            self.table.setCellWidget(i, 9, widget)
    
    def create_project(self):
        dialog = ProjectDialog(self.main, self.main.accounts, self.main.proxies, self.main.databases)
        if dialog.exec_():
            project = Project(
                name=dialog.name_input.text(),
                account_phone=dialog.account_combo.currentData(),
                proxy_string=dialog.proxy_combo.currentData() if dialog.proxy_combo.currentIndex() > 0 else None,
                channels_list=dialog.get_selected_channels(),
                comments_list=[c for c in dialog.comments_text.toPlainText().split('\n') if c.strip()],
                reply_text=dialog.reply_text.toPlainText(),
                delay_min=dialog.delay_min_spin.value(),
                delay_max=dialog.delay_max_spin.value(),
                subscribe_delay_min=dialog.subscribe_delay_min_spin.value(),
                subscribe_delay_max=dialog.subscribe_delay_max_spin.value(),
                auto_subscribe=dialog.auto_subscribe_check.isChecked(),
                auto_comment=dialog.auto_comment_check.isChecked(),
                auto_join_chat=dialog.auto_join_chat_check.isChecked(),
                auto_reply=dialog.auto_reply_check.isChecked(),
                comment_mode=dialog.comment_mode_combo.currentData(),
                photos_folder=dialog.photos_folder if hasattr(dialog, 'photos_folder') else "",
                pause_after_count=dialog.pause_after_count_spin.value(),
                pause_duration=dialog.pause_duration_spin.value()
            )
            self.main.projects.append(project)
            self.main.save_projects()
            self.refresh_table()
    
    def edit_project(self, index):
        project = self.main.projects[index]
        
        if project.is_running:
            QMessageBox.warning(self, "Предупреждение", "Остановите проект перед редактированием!")
            return
        
        dialog = ProjectDialog(self.main, self.main.accounts, self.main.proxies, self.main.databases, project)
        if dialog.exec_():
            project.name = dialog.name_input.text()
            project.account_phone = dialog.account_combo.currentData()
            project.proxy_string = dialog.proxy_combo.currentData() if dialog.proxy_combo.currentIndex() > 0 else None
            project.channels = dialog.get_selected_channels()
            project.comments = [c for c in dialog.comments_text.toPlainText().split('\n') if c.strip()]
            project.reply_text = dialog.reply_text.toPlainText()
            project.delay_min = dialog.delay_min_spin.value()
            project.delay_max = dialog.delay_max_spin.value()
            project.subscribe_delay_min = dialog.subscribe_delay_min_spin.value()
            project.subscribe_delay_max = dialog.subscribe_delay_max_spin.value()
            project.pause_after_count = dialog.pause_after_count_spin.value()
            project.pause_duration = dialog.pause_duration_spin.value()
            project.auto_subscribe = dialog.auto_subscribe_check.isChecked()
            project.auto_comment = dialog.auto_comment_check.isChecked()
            project.auto_join_chat = dialog.auto_join_chat_check.isChecked()
            project.auto_reply = dialog.auto_reply_check.isChecked()
            project.comment_mode = dialog.comment_mode_combo.currentData()
            if project.comment_mode == "photo" and hasattr(dialog, 'photos_folder'):
                project.photos_folder = dialog.photos_folder
                if os.path.exists(project.photos_folder):
                    project.photos_list = [f for f in os.listdir(project.photos_folder) 
                                          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
            
            self.main.save_projects()
            self.refresh_table()
            QMessageBox.information(self, "Успех", "Проект обновлен!")
    
    def start_project(self, index):
        project = self.main.projects[index]
        account = next((acc for acc in self.main.accounts if acc.phone == project.account_phone), None)
        if not account:
            QMessageBox.warning(self, "Ошибка", f"Аккаунт не найден!")
            return
        if not account.is_valid:
            QMessageBox.warning(self, "Ошибка", f"Аккаунт не валиден!")
            return
        
        if project.comment_mode == "photo":
            if not project.photos_folder or not os.path.exists(project.photos_folder):
                QMessageBox.warning(self, "Ошибка", "Папка с фото не найдена!")
                return
            if not project.photos_list:
                QMessageBox.warning(self, "Ошибка", "В папке с фото нет изображений!")
                return
        
        project.is_running = True
        project.subscribed_channels = []
        project.joined_chats = []
        project.skipped_channels = []
        project.last_post_ids = {}
        self.main.save_projects()
        self.refresh_table()
        thread = threading.Thread(target=self.run_project, args=(project, account), daemon=True)
        thread.start()
        project.thread = thread
    
    def run_project(self, project, account):
        asyncio.run(self.project_worker(project, account))
    
    async def project_worker(self, project, account):
        try:
            async with Client(account.session_path, api_id=API_ID, api_hash=API_HASH) as client:
                me = await client.get_me()
                print(f"✅ Проект {project.name} запущен. Режим: {project.comment_mode}")
                project.stats["last_action"] = f"Запущен (режим: {project.comment_mode})"
                
                subscribe_count = 0
                
                for channel in project.channels:
                    if not project.is_running:
                        break
                    
                    ch = channel.strip().replace("@", "").replace("https://t.me/", "")
                    
                    if ch in project.skipped_channels:
                        continue
                    
                    if project.auto_subscribe and ch not in project.subscribed_channels:
                        try:
                            await client.join_chat(ch)
                            project.stats["subscribes"] += 1
                            project.subscribed_channels.append(ch)
                            subscribe_count += 1
                            print(f"📢 Подписался на канал: {ch}")
                            
                            if project.pause_after_count > 0 and subscribe_count % project.pause_after_count == 0:
                                print(f"⏸ Промежуточная пауза после {subscribe_count} подписок: {project.pause_duration} сек")
                                project.stats["last_action"] = f"⏸ Пауза после {subscribe_count} подписок ({project.pause_duration}с)"
                                await asyncio.sleep(project.pause_duration)
                            else:
                                delay = random.randint(project.subscribe_delay_min, project.subscribe_delay_max)
                                await asyncio.sleep(delay)
                                
                        except FloodWait as e:
                            wait_time = e.value
                            print(f"⚠️ FloodWait на {ch}: принудительная пауза {wait_time} секунд")
                            project.stats["last_action"] = f"⏳ FloodWait {wait_time}с на {ch}"
                            await asyncio.sleep(wait_time)
                            try:
                                await client.join_chat(ch)
                                project.stats["subscribes"] += 1
                                project.subscribed_channels.append(ch)
                                subscribe_count += 1
                                print(f"📢 Повторная подписка на канал после FloodWait: {ch}")
                                delay = random.randint(project.subscribe_delay_min, project.subscribe_delay_max)
                                await asyncio.sleep(delay)
                            except (ChannelPrivate, InviteRequestSent) as e2:
                                project.skipped_channels.append(ch)
                                project.stats["skipped"] += 1
                                print(f"⛔ Пропуск приватного канала {ch}: {e2}")
                            except FloodWait as e2:
                                wait_time2 = e2.value
                                print(f"⚠️ Повторный FloodWait на {ch}: пауза {wait_time2} секунд")
                                project.stats["last_action"] = f"⏳ FloodWait {wait_time2}с на {ch}"
                                await asyncio.sleep(wait_time2)
                            except Exception as e2:
                                print(f"⚠️ Ошибка повторной подписки на {ch}: {e2}")
                        except (ChannelPrivate, InviteRequestSent) as e:
                            project.skipped_channels.append(ch)
                            project.stats["skipped"] += 1
                            print(f"⛔ Пропуск приватного канала {ch}: {e}")
                        except UserAlreadyParticipant:
                            project.subscribed_channels.append(ch)
                            print(f"ℹ️ Уже подписан на {ch}")
                        except Exception as e:
                            err_str = str(e).lower()
                            if "private" in err_str or "invite" in err_str or "request" in err_str:
                                project.skipped_channels.append(ch)
                                project.stats["skipped"] += 1
                                print(f"⛔ Пропуск канала {ch} (требуется заявка/приватный): {e}")
                            else:
                                print(f"⚠️ Ошибка подписки на {ch}: {e}")
                    
                    if ch in project.skipped_channels:
                        continue
                    
                    if ch not in project.chat_ids:
                        try:
                            chat = await client.get_chat(ch)
                            
                            linked_chat_id = None
                            linked_chat_username = None
                            
                            if hasattr(chat, 'linked_chat') and chat.linked_chat:
                                linked_chat_id = chat.linked_chat.id
                                linked_chat_username = chat.linked_chat.username
                                print(f"🔗 Найден чат обсуждения для {ch}: {linked_chat_username}")
                            elif hasattr(chat, 'discussion_chat_id') and chat.discussion_chat_id:
                                linked_chat_id = chat.discussion_chat_id
                                print(f"🔗 Найден чат обсуждения для {ch} (discussion_id: {linked_chat_id})")
                            
                            if linked_chat_id:
                                project.chat_ids[ch] = linked_chat_id
                                
                                if project.auto_join_chat and ch not in project.joined_chats:
                                    try:
                                        await client.join_chat(linked_chat_id)
                                        project.stats["chats_joined"] += 1
                                        project.joined_chats.append(ch)
                                        subscribe_count += 1
                                        print(f"💬 Вступил в чат обсуждения: {ch}")
                                        
                                        if project.pause_after_count > 0 and subscribe_count % project.pause_after_count == 0:
                                            print(f"⏸ Промежуточная пауза после {subscribe_count} подписок: {project.pause_duration} сек")
                                            project.stats["last_action"] = f"⏸ Пауза после {subscribe_count} подписок ({project.pause_duration}с)"
                                            await asyncio.sleep(project.pause_duration)
                                        else:
                                            delay = random.randint(project.subscribe_delay_min, project.subscribe_delay_max)
                                            await asyncio.sleep(delay)
                                            
                                    except FloodWait as e:
                                        wait_time = e.value
                                        print(f"⚠️ FloodWait при вступлении в чат {ch}: принудительная пауза {wait_time} секунд")
                                        project.stats["last_action"] = f"⏳ FloodWait {wait_time}с на чат {ch}"
                                        await asyncio.sleep(wait_time)
                                        try:
                                            await client.join_chat(linked_chat_id)
                                            project.stats["chats_joined"] += 1
                                            project.joined_chats.append(ch)
                                            subscribe_count += 1
                                            print(f"💬 Повторное вступление в чат после FloodWait: {ch}")
                                        except (ChannelPrivate, InviteRequestSent):
                                            project.skipped_channels.append(ch)
                                            project.stats["skipped"] += 1
                                            print(f"⛔ Пропуск приватного чата {ch}")
                                        except Exception as e2:
                                            print(f"⚠️ Ошибка повторного вступления в чат {ch}: {e2}")
                                    except (ChannelPrivate, InviteRequestSent) as e:
                                        project.skipped_channels.append(ch)
                                        project.stats["skipped"] += 1
                                        print(f"⛔ Пропуск приватного чата {ch}: {e}")
                                    except Exception as e:
                                        err_str = str(e).lower()
                                        if "private" in err_str or "invite" in err_str or "request" in err_str:
                                            project.skipped_channels.append(ch)
                                            project.stats["skipped"] += 1
                                            print(f"⛔ Пропуск чата {ch} (приватный/заявка): {e}")
                                        else:
                                            print(f"⚠️ Ошибка вступления в чат {ch}: {e}")
                                            if linked_chat_username:
                                                try:
                                                    await client.join_chat(linked_chat_username)
                                                    project.stats["chats_joined"] += 1
                                                    project.joined_chats.append(ch)
                                                    subscribe_count += 1
                                                    print(f"💬 Вступил в чат по username: {linked_chat_username}")
                                                except (ChannelPrivate, InviteRequestSent):
                                                    project.skipped_channels.append(ch)
                                                    project.stats["skipped"] += 1
                                                except FloodWait as e2:
                                                    wait_time = e2.value
                                                    project.stats["last_action"] = f"⏳ FloodWait {wait_time}с"
                                                    await asyncio.sleep(wait_time)
                                                except Exception as e2:
                                                    print(f"⚠️ Ошибка вступления в чат по username: {e2}")
                            else:
                                project.chat_ids[ch] = None
                                print(f"⚠️ Нет чата обсуждения для {ch}")
                        except (ChannelPrivate, InviteRequestSent) as e:
                            project.skipped_channels.append(ch)
                            project.stats["skipped"] += 1
                            print(f"⛔ Пропуск приватного канала {ch} при получении чата: {e}")
                            project.chat_ids[ch] = None
                        except Exception as e:
                            err_str = str(e).lower()
                            if "private" in err_str or "invite" in err_str:
                                project.skipped_channels.append(ch)
                                project.stats["skipped"] += 1
                                print(f"⛔ Пропуск канала {ch}: {e}")
                            else:
                                print(f"⚠️ Ошибка получения чата {ch}: {e}")
                            project.chat_ids[ch] = None
                
                # Запоминаем последние ID постов
                for channel in project.channels:
                    if not project.is_running:
                        break
                    
                    ch = channel.strip().replace("@", "").replace("https://t.me/", "")
                    chat_id = project.chat_ids.get(ch)
                    
                    if chat_id and project.auto_comment:
                        try:
                            async for msg in client.get_chat_history(chat_id, limit=1):
                                if msg and msg.id:
                                    project.last_post_ids[ch] = msg.id
                                    print(f"📌 Запомнен последний пост в {ch}: ID={msg.id}")
                                    break
                        except Exception as e:
                            print(f"⚠️ Ошибка получения последнего поста для {ch}: {e}")
                
                @client.on_message()
                async def handle_private_messages(client, message: Message):
                    if not project.is_running:
                        return
                    if not project.auto_reply:
                        return
                    if message.chat.type.value == "private":
                        if message.from_user and message.from_user.id != me.id:
                            try:
                                await message.reply(project.reply_text)
                                project.stats["replies"] += 1
                                project.stats["last_action"] = f"✉️ Ответил в ЛС {message.from_user.first_name}"
                                print(f"✉️ Ответил в ЛС {message.from_user.first_name}")
                            except Exception as e:
                                print(f"⚠️ Ошибка ответа в ЛС: {e}")
                
                # ОСНОВНОЙ ЦИКЛ КОММЕНТИРОВАНИЯ
                while project.is_running:
                    for channel in project.channels:
                        if not project.is_running:
                            break
                        
                        ch = channel.strip().replace("@", "").replace("https://t.me/", "")
                        chat_id = project.chat_ids.get(ch)
                        
                        if ch in project.skipped_channels:
                            continue
                        
                        if not chat_id or not project.auto_comment:
                            continue
                        
                        try:
                            # Получаем последние 5 сообщений из чата
                            async for msg in client.get_chat_history(chat_id, limit=5):
                                if not project.is_running:
                                    break
                                
                                # Проверяем, что это пост из канала (пересланное сообщение)
                                is_forwarded_from_channel = False
                                
                                # Проверка через forward_from_chat
                                if hasattr(msg, 'forward_from_chat') and msg.forward_from_chat:
                                    if hasattr(msg.forward_from_chat, 'type') and msg.forward_from_chat.type.value == "channel":
                                        is_forwarded_from_channel = True
                                    elif hasattr(msg.forward_from_chat, 'username') or hasattr(msg.forward_from_chat, 'title'):
                                        is_forwarded_from_channel = True
                                
                                # Проверка через fwd_from
                                if not is_forwarded_from_channel and hasattr(msg, 'fwd_from') and msg.fwd_from:
                                    if hasattr(msg.fwd_from, 'from_id') and msg.fwd_from.from_id:
                                        is_forwarded_from_channel = True
                                
                                # Проверяем, что сообщение не от нас
                                is_from_me = hasattr(msg, 'from_user') and msg.from_user and msg.from_user.id == me.id
                                
                                # Проверяем, что ID сообщения больше последнего обработанного
                                last_id = project.last_post_ids.get(ch, 0)
                                
                                if is_forwarded_from_channel and not is_from_me and msg.id > last_id:
                                    delay = random.randint(project.delay_min, project.delay_max)
                                    
                                    # Отправляем комментарий
                                    if project.comment_mode == "photo" and project.photos_list:
                                        photo_file = random.choice(project.photos_list)
                                        photo_path = os.path.join(project.photos_folder, photo_file)
                                        try:
                                            await client.send_photo(
                                                chat_id=chat_id,
                                                photo=photo_path,
                                                reply_to_message_id=msg.id
                                            )
                                            project.stats["comments"] += 1
                                            print(f"📷 Отправил фото в {ch}: {photo_file} (пост ID:{msg.id})")
                                            project.stats["last_action"] = f"📷 Фото в {ch}"
                                        except Exception as e:
                                            print(f"⚠️ Ошибка отправки фото в {ch}: {e}")
                                            if project.comments:
                                                comment = random.choice(project.comments)
                                                await client.send_message(chat_id, comment, reply_to_message_id=msg.id)
                                                project.stats["comments"] += 1
                                                print(f"💬 Комментарий в {ch} (замена фото, пост ID:{msg.id})")
                                    else:
                                        if project.comments:
                                            comment = random.choice(project.comments)
                                            await client.send_message(chat_id, comment, reply_to_message_id=msg.id)
                                            project.stats["comments"] += 1
                                            print(f"💬 Комментарий в {ch}: '{comment[:50]}...' (пост ID:{msg.id})")
                                            project.stats["last_action"] = f"💬 Коммент в {ch}"
                                    
                                    # Обновляем последний обработанный ID
                                    if msg.id > project.last_post_ids.get(ch, 0):
                                        project.last_post_ids[ch] = msg.id
                                    
                                    # Ждем задержку перед следующим комментарием
                                    await asyncio.sleep(delay)
                                else:
                                    # Обновляем last_id если нашли более новый пост
                                    if msg.id > project.last_post_ids.get(ch, 0):
                                        project.last_post_ids[ch] = msg.id
                            
                        except Exception as e:
                            print(f"⚠️ Ошибка обработки {ch}: {e}")
                            project.stats["errors"] += 1
                    
                    # Пауза между циклами проверки
                    if project.is_running:
                        await asyncio.sleep(10)
                
        except Exception as e:
            print(f"❌ Ошибка в проекте {project.name}: {e}")
            project.stats["errors"] += 1
            project.stats["last_action"] = f"Ошибка: {str(e)[:50]}"
        finally:
            project.is_running = False
            self.main.save_projects()
            self.refresh_signal.emit()
    
    def stop_project(self, index):
        self.main.projects[index].is_running = False
        self.main.save_projects()
        self.refresh_table()
    
    def stop_all(self):
        for p in self.main.projects:
            p.is_running = False
        self.main.save_projects()
        self.refresh_table()
    
    def delete_project(self, index):
        if QMessageBox.question(self, "Удаление", "Удалить проект?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.main.projects.pop(index)
            self.main.save_projects()
            self.refresh_table()

# ========== ДИАЛОГ ПРОЕКТА ==========
class ProjectDialog(QDialog):
    def __init__(self, main_window, accounts, proxies, databases, project=None):
        super().__init__(main_window)
        self.main = main_window
        self.accounts = accounts
        self.proxies = proxies
        self.databases = databases
        self.project = project
        self.photos_folder = ""
        self.setWindowTitle("Создать проект" if not project else "Редактировать проект")
        self.setModal(True)
        self.setMinimumSize(550, 600)
        self.resize(600, 700)
        
        self.setup_ui()
    
    def setup_ui(self):
        main_layout = QVBoxLayout()
        
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(10)
        
        layout.addWidget(QLabel("Название проекта:"))
        self.name_input = QLineEdit()
        if self.project:
            self.name_input.setText(self.project.name)
        layout.addWidget(self.name_input)
        
        layout.addWidget(QLabel("Аккаунт:"))
        self.account_combo = QComboBox()
        for acc in self.accounts:
            if acc.is_valid:
                self.account_combo.addItem(f"{acc.name} ({acc.phone})", acc.phone)
        if self.project:
            idx = self.account_combo.findData(self.project.account_phone)
            if idx >= 0:
                self.account_combo.setCurrentIndex(idx)
        layout.addWidget(self.account_combo)
        
        layout.addWidget(QLabel("Прокси:"))
        self.proxy_combo = QComboBox()
        self.proxy_combo.addItem("Без прокси", None)
        for p in self.proxies:
            if p.is_working:
                self.proxy_combo.addItem(p.proxy_string, p.proxy_string)
        if self.project and self.project.proxy_string:
            idx = self.proxy_combo.findData(self.project.proxy_string)
            if idx >= 0:
                self.proxy_combo.setCurrentIndex(idx)
        layout.addWidget(self.proxy_combo)
        
        mode_group = QGroupBox("🎯 Режим комментариев")
        mode_layout = QHBoxLayout()
        self.comment_mode_combo = QComboBox()
        self.comment_mode_combo.addItem("📝 Текстовые комментарии", "text")
        self.comment_mode_combo.addItem("📷 Фото из папки", "photo")
        self.comment_mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        if self.project:
            idx = 0 if self.project.comment_mode == "text" else 1
            self.comment_mode_combo.setCurrentIndex(idx)
        mode_layout.addWidget(self.comment_mode_combo)
        mode_group.setLayout(mode_layout)
        layout.addWidget(mode_group)
        
        self.photos_group = QGroupBox("📁 Папка с фотографиями")
        photos_layout = QVBoxLayout()
        self.photos_path_label = QLabel("Папка не выбрана")
        self.photos_path_label.setStyleSheet("color: #f38ba8;")
        self.select_photos_btn = QPushButton("📂 Выбрать папку с фото")
        self.select_photos_btn.clicked.connect(self.select_photos_folder)
        photos_layout.addWidget(self.photos_path_label)
        photos_layout.addWidget(self.select_photos_btn)
        self.photos_group.setLayout(photos_layout)
        layout.addWidget(self.photos_group)
        
        if self.project and self.project.comment_mode == "photo" and self.project.photos_folder:
            self.photos_folder = self.project.photos_folder
            self.photos_path_label.setText(f"📁 {self.project.photos_folder} ({len(self.project.photos_list)} фото)")
            self.photos_path_label.setStyleSheet("color: #a6e3a1;")
        
        if self.project and self.project.comment_mode == "text":
            self.photos_group.setVisible(False)
        
        subscribe_group = QGroupBox("📢 Настройки подписок и вступлений")
        subscribe_layout = QGridLayout()
        
        self.auto_subscribe_check = QCheckBox("✅ Подписываться на каналы")
        self.auto_subscribe_check.setChecked(self.project.auto_subscribe if self.project else True)
        subscribe_layout.addWidget(self.auto_subscribe_check, 0, 0, 1, 2)
        
        self.auto_join_chat_check = QCheckBox("💬 Вступать в чаты обсуждения")
        self.auto_join_chat_check.setChecked(self.project.auto_join_chat if self.project else True)
        subscribe_layout.addWidget(self.auto_join_chat_check, 1, 0, 1, 2)
        
        subscribe_layout.addWidget(QLabel("Мин. задержка между подписками (сек):"), 2, 0)
        self.subscribe_delay_min_spin = QSpinBox()
        self.subscribe_delay_min_spin.setRange(2, 60)
        self.subscribe_delay_min_spin.setValue(self.project.subscribe_delay_min if self.project else 5)
        subscribe_layout.addWidget(self.subscribe_delay_min_spin, 2, 1)
        
        subscribe_layout.addWidget(QLabel("Макс. задержка между подписками (сек):"), 3, 0)
        self.subscribe_delay_max_spin = QSpinBox()
        self.subscribe_delay_max_spin.setRange(3, 120)
        self.subscribe_delay_max_spin.setValue(self.project.subscribe_delay_max if self.project else 10)
        subscribe_layout.addWidget(self.subscribe_delay_max_spin, 3, 1)
        
        subscribe_layout.addWidget(QLabel("⏸ Пауза после каждых N подписок (0 = выкл):"), 4, 0)
        self.pause_after_count_spin = QSpinBox()
        self.pause_after_count_spin.setRange(0, 1000)
        self.pause_after_count_spin.setValue(self.project.pause_after_count if self.project else 0)
        subscribe_layout.addWidget(self.pause_after_count_spin, 4, 1)
        
        subscribe_layout.addWidget(QLabel("Длительность паузы (сек):"), 5, 0)
        self.pause_duration_spin = QSpinBox()
        self.pause_duration_spin.setRange(10, 3600)
        self.pause_duration_spin.setValue(self.project.pause_duration if self.project else 60)
        subscribe_layout.addWidget(self.pause_duration_spin, 5, 1)
        
        subscribe_group.setLayout(subscribe_layout)
        layout.addWidget(subscribe_group)
        
        comment_group = QGroupBox("✏️ Настройки комментариев")
        comment_layout = QGridLayout()
        
        self.auto_comment_check = QCheckBox("Комментировать посты в каналах")
        self.auto_comment_check.setChecked(self.project.auto_comment if self.project else True)
        comment_layout.addWidget(self.auto_comment_check, 0, 0, 1, 2)
        
        comment_layout.addWidget(QLabel("Мин. задержка между комментариями (сек):"), 1, 0)
        self.delay_min_spin = QSpinBox()
        self.delay_min_spin.setRange(5, 300)
        self.delay_min_spin.setValue(self.project.delay_min if self.project else 15)
        comment_layout.addWidget(self.delay_min_spin, 1, 1)
        
        comment_layout.addWidget(QLabel("Макс. задержка между комментариями (сек):"), 2, 0)
        self.delay_max_spin = QSpinBox()
        self.delay_max_spin.setRange(10, 600)
        self.delay_max_spin.setValue(self.project.delay_max if self.project else 30)
        comment_layout.addWidget(self.delay_max_spin, 2, 1)
        
        comment_group.setLayout(comment_layout)
        layout.addWidget(comment_group)
        
        reply_group = QGroupBox("✉️ Автоответ в личные сообщения")
        reply_layout = QGridLayout()
        
        self.auto_reply_check = QCheckBox("Отвечать на сообщения в ЛС")
        self.auto_reply_check.setChecked(self.project.auto_reply if self.project else True)
        reply_layout.addWidget(self.auto_reply_check, 0, 0, 1, 2)
        
        reply_layout.addWidget(QLabel("Текст ответа:"), 1, 0, 1, 2)
        self.reply_text = QTextEdit()
        self.reply_text.setMaximumHeight(80)
        if self.project:
            self.reply_text.setText(self.project.reply_text)
        else:
            self.reply_text.setText("Привет! Спасибо за сообщение. Я сейчас занят, обязательно отвечу позже.")
        reply_layout.addWidget(self.reply_text, 2, 0, 1, 2)
        
        reply_group.setLayout(reply_layout)
        layout.addWidget(reply_group)
        
        layout.addWidget(QLabel("База каналов:"))
        self.db_combo = QComboBox()
        self.db_combo.addItem("-- Свой список --", None)
        for db in self.databases:
            self.db_combo.addItem(f"📁 {db['name']} ({len(db.get('channels', []))} каналов)", db)
        self.db_combo.currentIndexChanged.connect(self.on_db_selected)
        layout.addWidget(self.db_combo)
        
        layout.addWidget(QLabel("Каналы (по одному на строку):"))
        layout.addWidget(QLabel("Пример: @channel_name или https://t.me/channel_name"))
        self.channels_text = QTextEdit()
        self.channels_text.setMaximumHeight(120)
        if self.project:
            self.channels_text.setText("\n".join(self.project.channels))
        layout.addWidget(self.channels_text)
        
        layout.addWidget(QLabel("Комментарии (по одному на строку):"))
        self.comments_text = QTextEdit()
        self.comments_text.setMaximumHeight(120)
        if self.project:
            self.comments_text.setText("\n".join(self.project.comments))
        else:
            self.comments_text.setText("Отличный пост!\nСпасибо!\n👍\n🔥\nИнтересно\nПодписался")
        layout.addWidget(self.comments_text)
        
        btn_layout = QHBoxLayout()
        ok_btn = QPushButton("Сохранить")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        layout.addSpacing(20)
        
        scroll_area.setWidget(container)
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout)
    
    def on_mode_changed(self, index):
        mode = self.comment_mode_combo.currentData()
        self.photos_group.setVisible(mode == "photo")
    
    def select_photos_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с фотографиями")
        if folder:
            photos = [f for f in os.listdir(folder) 
                     if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp'))]
            if photos:
                self.photos_folder = folder
                self.photos_path_label.setText(f"📁 {folder} ({len(photos)} фото)")
                self.photos_path_label.setStyleSheet("color: #a6e3a1;")
                QMessageBox.information(self, "Успех", f"Найдено {len(photos)} фотографий")
            else:
                QMessageBox.warning(self, "Ошибка", "В выбранной папке нет фотографий!")
    
    def on_db_selected(self, index):
        db = self.db_combo.currentData()
        if db and db.get("channels"):
            channels = "\n".join([ch.get("link", ch.get("name", "")) for ch in db["channels"]])
            self.channels_text.setText(channels)
    
    def get_selected_channels(self):
        return [c.strip() for c in self.channels_text.toPlainText().split('\n') if c.strip()]

# ========== ВКЛАДКА TELEGRAM SIMILAR PARSER (С ФИЛЬТРАМИ) ==========
class SimilarParserTab(QWidget):
    update_results_signal = pyqtSignal()
    parse_finished_signal = pyqtSignal()
    log_signal = pyqtSignal(str)
    error_signal = pyqtSignal(str)
    
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.results = []
        self.is_parsing = False
        self.telegram_accounts = []
        self.setup_ui()
        self.update_results_signal.connect(self.update_results_table)
        self.parse_finished_signal.connect(self.on_parse_finished)
        self.log_signal.connect(self.add_log)
        self.error_signal.connect(self.show_error)
        
        QTimer.singleShot(100, self.refresh_telegram_accounts_table)
    
    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Информационная панель
        info_frame = QFrame()
        info_frame.setStyleSheet("background-color: #313244; border-radius: 8px; padding: 8px;")
        info_layout = QHBoxLayout(info_frame)
        info_label = QLabel(f"📁 Для работы парсера поместите файлы .session (Telethon) в папку: {TELEGRAM_SESSIONS_DIR}")
        info_label.setStyleSheet("color: #a6e3a1;")
        info_layout.addWidget(info_label)
        layout.addWidget(info_frame)
        
        # Таблица аккаунтов парсера
        btn_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("🔄 Обновить список сессий")
        self.refresh_btn.clicked.connect(self.refresh_telegram_accounts_table)
        self.remove_btn = QPushButton("🗑 Удалить выбранные из списка")
        self.remove_btn.clicked.connect(self.remove_selected_accounts)
        btn_layout.addWidget(self.refresh_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Телефон", "Имя аккаунта", "Путь к сессии"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.table)
        
        # Настройки парсинга
        parse_group = QGroupBox("🔍 Настройки парсинга")
        parse_layout = QGridLayout()
        
        parse_layout.addWidget(QLabel("Аккаунт для парсинга:"), 0, 0)
        self.account_combo = QComboBox()
        parse_layout.addWidget(self.account_combo, 0, 1)
        
        parse_layout.addWidget(QLabel("Прокси (опционально):"), 1, 0)
        self.proxy_combo = QComboBox()
        self.proxy_combo.addItem("Без прокси", None)
        parse_layout.addWidget(self.proxy_combo, 1, 1)
        
        parse_layout.addWidget(QLabel("Исходные каналы (по одному на строку):"), 2, 0, 1, 2)
        parse_layout.addWidget(QLabel("Пример: @channel_name или https://t.me/channel_name"), 3, 0, 1, 2)
        self.source_channels = QTextEdit()
        self.source_channels.setMaximumHeight(100)
        parse_layout.addWidget(self.source_channels, 4, 0, 1, 2)
        
        parse_layout.addWidget(QLabel("Задержка между запросами (сек):"), 5, 0)
        self.delay_spin = QSpinBox()
        self.delay_spin.setRange(1, 30)
        self.delay_spin.setValue(5)
        parse_layout.addWidget(self.delay_spin, 5, 1)
        
        self.parse_btn = QPushButton("🚀 НАЧАТЬ ПАРСИНГ")
        self.parse_btn.setStyleSheet("background-color: #4CAF50; color: white; font-size: 14px;")
        self.parse_btn.clicked.connect(self.start_parsing)
        parse_layout.addWidget(self.parse_btn, 6, 0, 1, 2)
        
        parse_group.setLayout(parse_layout)
        layout.addWidget(parse_group)
        
        # Лог
        layout.addWidget(QLabel("📝 Лог:"))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        layout.addWidget(self.log_text)
        
        # Результаты
        results_group = QGroupBox("📋 Результаты парсинга")
        results_layout = QVBoxLayout()
        
        # Кнопки фильтрации
        filter_layout = QHBoxLayout()
        self.only_comments_btn = QPushButton("💬 Только с комментариями")
        self.only_comments_btn.clicked.connect(self.filter_only_comments)
        self.filter_lang_btn = QPushButton("🌍 Фильтр по языку")
        self.filter_lang_btn.clicked.connect(self.filter_by_language)
        self.combined_filter_btn = QPushButton("🎛 Комбинированный фильтр")
        self.combined_filter_btn.setStyleSheet("background-color: #f9e2af; color: #1e1e2e;")
        self.combined_filter_btn.clicked.connect(self.combined_filter)
        self.select_all_btn = QPushButton("✅ Выделить всё")
        self.select_all_btn.clicked.connect(self.select_all)
        self.deselect_all_btn = QPushButton("❌ Снять всё")
        self.deselect_all_btn.clicked.connect(self.deselect_all)
        
        filter_layout.addWidget(self.only_comments_btn)
        filter_layout.addWidget(self.filter_lang_btn)
        filter_layout.addWidget(self.combined_filter_btn)
        filter_layout.addWidget(self.select_all_btn)
        filter_layout.addWidget(self.deselect_all_btn)
        results_layout.addLayout(filter_layout)
        
        self.active_filters_label = QLabel("")
        self.active_filters_label.setStyleSheet("color: #f9e2af; font-size: 11px; padding: 2px 5px;")
        results_layout.addWidget(self.active_filters_label)
        
        # Таблица результатов с чекбоксами
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(5)
        self.results_table.setHorizontalHeaderLabels(["Выбрать", "Язык", "Username", "Название", "Комментарии"])
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        results_layout.addWidget(self.results_table)
        
        # Кнопки действий
        action_layout = QHBoxLayout()
        self.save_db_btn = QPushButton("💾 Сохранить выбранные в базу")
        self.save_db_btn.clicked.connect(self.save_selected_to_database)
        self.save_db_btn.setStyleSheet("background-color: #a6e3a1; color: #1e1e2e;")
        self.export_btn = QPushButton("📁 Экспорт выбранных в файл")
        self.export_btn.clicked.connect(self.export_selected)
        self.clear_btn = QPushButton("🗑 Очистить результаты")
        self.clear_btn.clicked.connect(self.clear_results)
        
        action_layout.addWidget(self.save_db_btn)
        action_layout.addWidget(self.export_btn)
        action_layout.addWidget(self.clear_btn)
        results_layout.addLayout(action_layout)
        
        results_group.setLayout(results_layout)
        layout.addWidget(results_group)
        
        self.setLayout(layout)
        
        # Состояние фильтров
        self.active_filter_state = {"only_comments": False, "selected_langs": None}
        self.checkboxes = []
    
    def refresh_telegram_accounts_table(self):
        try:
            self.telegram_accounts = []
            
            if os.path.exists(TELEGRAM_SESSIONS_DIR):
                for file in os.listdir(TELEGRAM_SESSIONS_DIR):
                    if file.endswith('.session'):
                        session_path = os.path.join(TELEGRAM_SESSIONS_DIR, file)
                        session_name = file.replace('.session', '')
                        
                        phone = self.extract_phone_from_session(session_path)
                        if phone:
                            name = f"Аккаунт {phone}"
                        else:
                            name = f"Сессия: {session_name}"
                        
                        self.telegram_accounts.append({
                            'phone': phone if phone else session_name,
                            'name': name,
                            'session_path': session_path
                        })
            
            self.table.setRowCount(len(self.telegram_accounts))
            for i, acc in enumerate(self.telegram_accounts):
                self.table.setItem(i, 0, QTableWidgetItem(acc['phone']))
                self.table.setItem(i, 1, QTableWidgetItem(acc['name']))
                self.table.setItem(i, 2, QTableWidgetItem(acc['session_path']))
            self.table.resizeColumnsToContents()
            
            self.update_combos()
            
            if not self.telegram_accounts:
                self.log_signal.emit(f"ℹ️ Сессии не найдены. Поместите .session файлы в папку: {TELEGRAM_SESSIONS_DIR}")
            else:
                self.log_signal.emit(f"✅ Загружено {len(self.telegram_accounts)} сессий")
                
        except Exception as e:
            self.error_signal.emit(f"Ошибка загрузки сессий: {str(e)}")
    
    def extract_phone_from_session(self, session_path):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def get_phone():
                try:
                    client = TelethonClient(session_path, API_ID, API_HASH)
                    await client.connect()
                    if await client.is_user_authorized():
                        me = await client.get_me()
                        await client.disconnect()
                        return me.phone if me.phone else None
                    await client.disconnect()
                    return None
                except Exception:
                    return None
            
            phone = loop.run_until_complete(get_phone())
            loop.close()
            return phone
        except Exception:
            return None
    
    def update_combos(self):
        self.account_combo.clear()
        self.proxy_combo.clear()
        
        for acc in self.telegram_accounts:
            display = f"{acc['name']} ({acc['phone']})" if acc['phone'] != acc['name'] else acc['name']
            self.account_combo.addItem(display, acc['session_path'])
        
        if not self.telegram_accounts:
            self.account_combo.addItem("-- Нет сессий --", None)
        
        self.proxy_combo.addItem("Без прокси", None)
        for p in self.main.proxies:
            if p.is_working:
                self.proxy_combo.addItem(p.proxy_string, p.proxy_string)
    
    def remove_selected_accounts(self):
        selected = self.table.selectedItems()
        if selected:
            rows = set(item.row() for item in selected)
            if QMessageBox.question(self, "Удаление", 
                f"Удалить {len(rows)} сессий из списка?\n(Файлы .session останутся в папке)",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                for row in sorted(rows, reverse=True):
                    if row < len(self.telegram_accounts):
                        self.telegram_accounts.pop(row)
                self.refresh_telegram_accounts_table()
    
    @pyqtSlot(str)
    def add_log(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {text}")
    
    @pyqtSlot(str)
    def show_error(self, msg):
        QMessageBox.critical(self, "Ошибка", msg)
    
    def start_parsing(self):
        if self.is_parsing:
            QMessageBox.warning(self, "Ошибка", "Парсинг уже запущен!")
            return
        
        source_text = self.source_channels.toPlainText()
        if not source_text:
            QMessageBox.warning(self, "Ошибка", "Введите исходные каналы!")
            return
        
        if not self.telegram_accounts:
            QMessageBox.warning(self, "Ошибка", 
                f"Нет сессий!\nПоместите файлы .session (Telethon) в папку:\n{TELEGRAM_SESSIONS_DIR}\nи нажмите 'Обновить список сессий'")
            return
        
        session_path = self.account_combo.currentData()
        if not session_path:
            QMessageBox.warning(self, "Ошибка", "Выберите аккаунт для парсинга!")
            return
        
        source_channels = [c.strip().replace("@", "").replace("https://t.me/", "") 
                          for c in source_text.split('\n') if c.strip()]
        
        proxy_string = self.proxy_combo.currentData()
        delay = self.delay_spin.value()
        
        self.results = []
        self.is_parsing = True
        self.parse_btn.setEnabled(False)
        self.parse_btn.setText("⏳ ПАРСИНГ...")
        self.log_text.clear()
        self.results_table.setRowCount(0)
        
        threading.Thread(target=self.parse_thread, args=(source_channels, session_path, proxy_string, delay), daemon=True).start()
    
    def parse_thread(self, source_channels, session_path, proxy_string, delay_between):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self.async_parse(source_channels, session_path, proxy_string, delay_between))
        except Exception as e:
            self.error_signal.emit(f"Ошибка в потоке парсинга: {str(e)}")
        finally:
            loop.close()
    
    async def async_parse(self, source_channels, session_path, proxy_string, delay_between):
        proxy_dict = None
        if proxy_string:
            match = re.match(r'^(socks5|http|https)://(([^:]+):([^@]+)@)?([^:]+):(\d+)$', proxy_string)
            if match:
                proxy_type = match.group(1)
                username = match.group(3)
                password = match.group(4)
                host = match.group(5)
                port = int(match.group(6))
                proxy_dict = {
                    'proxy_type': proxy_type,
                    'addr': host,
                    'port': port,
                    'username': username,
                    'password': password
                }
        
        try:
            async with TelethonClient(session_path, API_ID, API_HASH, proxy=proxy_dict) as client:
                me = await client.get_me()
                self.log_signal.emit(f"✅ Авторизован как {me.first_name or me.username} ({me.phone})")
                
                all_found = {}
                
                for source in source_channels:
                    if not self.is_parsing:
                        break
                    
                    self.log_signal.emit(f"🔍 Парсинг похожих каналов для: {source}")
                    
                    try:
                        entity = await client.get_input_entity(source)
                        if isinstance(entity, (types.InputChannel, types.InputPeerChannel)):
                            input_channel = types.InputChannel(channel_id=entity.channel_id, access_hash=entity.access_hash)
                            result = await self.safe_api_request(
                                client(functions.channels.GetChannelRecommendationsRequest(channel=input_channel)),
                                'похожие каналы'
                            )
                            
                            if result and result.chats:
                                self.log_signal.emit(f"  📊 Найдено каналов: {len(result.chats)}")
                                for ch in result.chats:
                                    if ch.username and ch.username not in all_found:
                                        try:
                                            can_comment = await self.check_can_comment(client, ch.username)
                                            language = self.detect_language(ch.title)
                                            all_found[ch.username] = {
                                                'username': ch.username,
                                                'title': ch.title,
                                                'id': ch.id,
                                                'can_comment': can_comment,
                                                'link': f"https://t.me/{ch.username}",
                                                'language': language
                                            }
                                            comment_status = "✅ Можно комм." if can_comment else "❌ Нет чата"
                                            lang_emoji = {"ru": "🇷🇺", "en": "🇬🇧", "ar": "🇸🇦", "zh": "🇨🇳", "other": "🌐", "unknown": "❓"}.get(language, "❓")
                                            self.log_signal.emit(f"  📌 {lang_emoji} @{ch.username} - {ch.title[:40]}... ({comment_status})")
                                        except Exception as e:
                                            self.log_signal.emit(f"  ⚠️ Ошибка проверки канала @{ch.username}: {str(e)[:50]}")
                            else:
                                self.log_signal.emit(f"  ⚠️ Не найдено похожих каналов для {source}")
                        else:
                            self.log_signal.emit(f"  ⚠️ {source} не является каналом")
                    
                    except Exception as e:
                        self.log_signal.emit(f"  ❌ Ошибка при парсинге {source}: {str(e)[:100]}")
                    
                    await asyncio.sleep(delay_between)

                self.results = list(all_found.values())
                self.results.sort(key=lambda x: (x.get('language', 'unknown'), x['username']))

                can_comment_count = sum(1 for r in self.results if r['can_comment'])
                lang_stats = {}
                for r in self.results:
                    lang = r.get('language', 'unknown')
                    lang_stats[lang] = lang_stats.get(lang, 0) + 1
                lang_report = ", ".join([f"{lang}: {count}" for lang, count in sorted(lang_stats.items())])
                
                self.log_signal.emit(f"✅ Парсинг завершен! Найдено уникальных каналов: {len(self.results)} (из них с комментариями: {can_comment_count})")
                self.log_signal.emit(f"📊 По языкам: {lang_report}")
                
        except Exception as e:
            self.log_signal.emit(f"❌ Критическая ошибка: {str(e)}")
        
        finally:
            self.is_parsing = False
            self.parse_finished_signal.emit()
    
    async def safe_api_request(self, coroutine, comment):
        try:
            return await coroutine
        except RpcCallFailError as e:
            self.log_signal.emit(f"❌ API ошибка ({comment}): {str(e)[:100]}")
        except Exception as e:
            self.log_signal.emit(f"❌ Ошибка ({comment}): {str(e)[:100]}")
        return None
    
    def detect_language(self, text):
        if not text:
            return "unknown"
        
        cyrillic = sum(1 for c in text if 'Ѐ' <= c <= 'ӿ')
        latin = sum(1 for c in text if ('a' <= c.lower() <= 'z'))
        arabic = sum(1 for c in text if '؀' <= c <= 'ۿ')
        chinese = sum(1 for c in text if '一' <= c <= '鿿')
        
        total = cyrillic + latin + arabic + chinese
        if total == 0:
            return "unknown"
        
        if cyrillic / total > 0.3:
            return "ru"
        elif arabic / total > 0.3:
            return "ar"
        elif chinese / total > 0.3:
            return "zh"
        elif latin / total > 0.3:
            return "en"
        else:
            return "other"
    
    async def check_can_comment(self, client, username):
        try:
            entity = await client.get_input_entity(username)
            full_channel = await client(functions.channels.GetFullChannelRequest(channel=entity))
            
            if hasattr(full_channel.full_chat, 'linked_chat_id') and full_channel.full_chat.linked_chat_id:
                return True
            
            if hasattr(full_channel, 'chats') and full_channel.chats:
                for chat in full_channel.chats:
                    if hasattr(chat, 'megagroup') and chat.megagroup:
                        return True
                    if hasattr(chat, 'group') and chat.group:
                        return True
            
            return False
        except Exception:
            try:
                entity = await client.get_entity(username)
                full = await client.get_full_entity(entity)
                
                if hasattr(full, 'full_chat') and full.full_chat:
                    if hasattr(full.full_chat, 'linked_chat_id') and full.full_chat.linked_chat_id:
                        return True
                
                if hasattr(entity, 'megagroup') and entity.megagroup:
                    return True
                if hasattr(entity, 'group') and entity.group:
                    return True
                
                return False
            except Exception:
                return False
    
    @pyqtSlot()
    def on_parse_finished(self):
        self.parse_btn.setEnabled(True)
        self.parse_btn.setText("🚀 НАЧАТЬ ПАРСИНГ")
        
        if self.results:
            self.update_results_table()
            self.active_filter_state = {"only_comments": False, "selected_langs": None}
            self.active_filters_label.setText("")
            self.log_signal.emit(f"📋 Результаты отображены в таблице ({len(self.results)} каналов)")
        else:
            self.log_signal.emit("📭 Не найдено ни одного канала")
            QMessageBox.information(self, "📭 Результаты", "Не найдено ни одного канала")
    
    @pyqtSlot()
    def update_results_table(self):
        self.results_table.setRowCount(len(self.results))
        self.checkboxes = []
        
        lang_emoji = {"ru": "🇷🇺", "en": "🇬🇧", "ar": "🇸🇦", "zh": "🇨🇳", "other": "🌐", "unknown": "❓"}
        
        for i, res in enumerate(self.results):
            # Чекбокс
            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            cb = QCheckBox()
            cb.setChecked(res['can_comment'])
            cb_layout.addWidget(cb)
            cb_layout.addStretch()
            self.results_table.setCellWidget(i, 0, cb_widget)
            
            # Язык
            lang = res.get('language', 'unknown')
            lang_label = QLabel(lang_emoji.get(lang, "❓"))
            lang_label.setToolTip(lang)
            self.results_table.setCellWidget(i, 1, lang_label)
            
            # Username
            self.results_table.setItem(i, 2, QTableWidgetItem(f"@{res['username']}"))
            self.results_table.item(i, 2).setForeground(QColor("#89b4fa"))
            
            # Название
            self.results_table.setItem(i, 3, QTableWidgetItem(res['title'][:80]))
            
            # Комментарии
            comments_text = "✅ Да" if res['can_comment'] else "❌ Нет"
            comments_item = QTableWidgetItem(comments_text)
            if res['can_comment']:
                comments_item.setForeground(QColor("#a6e3a1"))
            else:
                comments_item.setForeground(QColor("#f38ba8"))
            self.results_table.setItem(i, 4, comments_item)
            
            self.checkboxes.append((cb, res))
        
        self.results_table.resizeColumnsToContents()
        self.results_table.setColumnWidth(0, 60)
        self.results_table.setColumnWidth(1, 50)
        self.results_table.setColumnWidth(2, 150)
    
    def filter_only_comments(self):
        for cb, res in self.checkboxes:
            cb.setChecked(res['can_comment'])
        self.active_filter_state["only_comments"] = True
        self.active_filter_state["selected_langs"] = None
        count = sum(1 for cb, res in self.checkboxes if res['can_comment'])
        self.active_filters_label.setText(f"🎛 Активные фильтры: только с комментариями | Отмечено: {count}/{len(self.checkboxes)}")
        QMessageBox.information(self, "Готово", f"Отмечены только каналы с комментариями ({count} шт.)")
    
    def filter_by_language(self):
        available_langs = set()
        for cb, res in self.checkboxes:
            available_langs.add(res.get('language', 'unknown'))
        
        lang_names = {
            "ru": "🇷🇺 Русский",
            "en": "🇬🇧 Английский",
            "ar": "🇸🇦 Арабский",
            "zh": "🇨🇳 Китайский",
            "other": "🌐 Другие",
            "unknown": "❓ Неизвестный"
        }
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Фильтр по языку")
        dialog.setModal(True)
        dialog.setFixedSize(350, 300)
        dialog.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QCheckBox { color: #cdd6f4; spacing: 8px; padding: 5px; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        ld_layout = QVBoxLayout(dialog)
        ld_layout.addWidget(QLabel("Выберите один или несколько языков:"))
        
        lang_checkboxes = {}
        for lang_code in sorted(available_langs):
            name = lang_names.get(lang_code, lang_code)
            lcb = QCheckBox(name)
            lcb.setChecked(True)
            ld_layout.addWidget(lcb)
            lang_checkboxes[lang_code] = lcb
        
        ld_layout.addStretch()
        ld_btn_layout = QHBoxLayout()
        ld_apply = QPushButton("Применить")
        ld_cancel = QPushButton("Отмена")
        ld_btn_layout.addWidget(ld_apply)
        ld_btn_layout.addWidget(ld_cancel)
        ld_layout.addLayout(ld_btn_layout)
        
        ld_apply.clicked.connect(dialog.accept)
        ld_cancel.clicked.connect(dialog.reject)
        
        if dialog.exec_() == QDialog.Accepted:
            selected_langs = {code for code, lcb in lang_checkboxes.items() if lcb.isChecked()}
            if not selected_langs:
                QMessageBox.warning(self, "Ошибка", "Не выбрано ни одного языка!")
                return
            
            self.active_filter_state["only_comments"] = False
            self.active_filter_state["selected_langs"] = selected_langs
            
            count = 0
            for cb, res in self.checkboxes:
                if res.get('language', 'unknown') in selected_langs:
                    cb.setChecked(True)
                    count += 1
                else:
                    cb.setChecked(False)
            
            lang_text = ", ".join(lang_names.get(l, l) for l in selected_langs)
            self.active_filters_label.setText(f"🎛 Активные фильтры: языки: {lang_text} | Отмечено: {count}/{len(self.checkboxes)}")
            QMessageBox.information(self, "Готово", f"Отмечено каналов: {count}\nЯзыки: {lang_text}")
    
    def combined_filter(self):
        available_langs = set()
        for cb, res in self.checkboxes:
            available_langs.add(res.get('language', 'unknown'))
        
        lang_names = {
            "ru": "🇷🇺 Русский",
            "en": "🇬🇧 Английский",
            "ar": "🇸🇦 Арабский",
            "zh": "🇨🇳 Китайский",
            "other": "🌐 Другие",
            "unknown": "❓ Неизвестный"
        }
        
        dialog = QDialog(self)
        dialog.setWindowTitle("🎛 Комбинированный фильтр")
        dialog.setModal(True)
        dialog.setFixedSize(450, 450)
        dialog.setStyleSheet("""
            QDialog { background-color: #1e1e2e; }
            QLabel { color: #cdd6f4; }
            QGroupBox { color: #cdd6f4; border: 1px solid #313244; border-radius: 6px; margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QCheckBox { color: #cdd6f4; spacing: 8px; padding: 3px; }
            QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
            QPushButton:hover { background-color: #b4befe; }
        """)
        
        cf_layout = QVBoxLayout(dialog)
        cf_layout.addWidget(QLabel("Настройте все фильтры и нажмите 'Применить'.\nКаналы должны соответствовать ВСЕМ выбранным критериям."))
        
        comments_group = QGroupBox("💬 Комментарии")
        cg_layout = QVBoxLayout()
        comments_filter_cb = QCheckBox("Только каналы с комментариями")
        comments_filter_cb.setChecked(self.active_filter_state.get("only_comments", False))
        cg_layout.addWidget(comments_filter_cb)
        comments_group.setLayout(cg_layout)
        cf_layout.addWidget(comments_group)
        
        lang_group = QGroupBox("🌍 Языки (выберите нужные)")
        lg_layout = QVBoxLayout()
        lang_select_all_cb = QCheckBox("Все языки")
        previously_selected = self.active_filter_state.get("selected_langs")
        all_selected = (previously_selected is None or previously_selected == available_langs)
        lang_select_all_cb.setChecked(all_selected)
        lg_layout.addWidget(lang_select_all_cb)
        
        lang_cbs = {}
        for lang_code in sorted(available_langs):
            name = lang_names.get(lang_code, lang_code)
            lcb = QCheckBox(name)
            lcb.setChecked(previously_selected is None or lang_code in previously_selected)
            lg_layout.addWidget(lcb)
            lang_cbs[lang_code] = lcb
        
        def toggle_all_langs(state):
            for lcb in lang_cbs.values():
                lcb.setChecked(state == Qt.Checked)
        
        def update_select_all():
            all_checked = all(lcb.isChecked() for lcb in lang_cbs.values())
            lang_select_all_cb.blockSignals(True)
            lang_select_all_cb.setChecked(all_checked)
            lang_select_all_cb.blockSignals(False)
        
        lang_select_all_cb.stateChanged.connect(toggle_all_langs)
        for lcb in lang_cbs.values():
            lcb.stateChanged.connect(update_select_all)
        
        lang_group.setLayout(lg_layout)
        cf_layout.addWidget(lang_group)
        
        cf_layout.addStretch()
        
        cf_btn_layout = QHBoxLayout()
        cf_apply = QPushButton("✅ Применить фильтры")
        cf_apply.setStyleSheet("background-color: #a6e3a1; color: #1e1e2e; border: none; padding: 10px 20px; border-radius: 6px; font-weight: bold; font-size: 13px;")
        cf_cancel = QPushButton("Отмена")
        cf_btn_layout.addWidget(cf_apply)
        cf_btn_layout.addWidget(cf_cancel)
        cf_layout.addLayout(cf_btn_layout)
        
        cf_apply.clicked.connect(dialog.accept)
        cf_cancel.clicked.connect(dialog.reject)
        
        if dialog.exec_() == QDialog.Accepted:
            only_with_comments = comments_filter_cb.isChecked()
            selected_langs = {code for code, lcb in lang_cbs.items() if lcb.isChecked()}
            
            if not selected_langs:
                QMessageBox.warning(self, "Ошибка", "Не выбрано ни одного языка!")
                return
            
            self.active_filter_state["only_comments"] = only_with_comments
            self.active_filter_state["selected_langs"] = selected_langs
            
            count = 0
            for cb, res in self.checkboxes:
                lang_ok = res.get('language', 'unknown') in selected_langs
                comment_ok = (not only_with_comments) or res.get('can_comment', False)
                if lang_ok and comment_ok:
                    cb.setChecked(True)
                    count += 1
                else:
                    cb.setChecked(False)
            
            filters_desc = []
            if only_with_comments:
                filters_desc.append("с комментариями")
            if len(selected_langs) < len(available_langs):
                lang_text = ", ".join(lang_names.get(l, l) for l in selected_langs)
                filters_desc.append(f"языки: {lang_text}")
            
            self.active_filters_label.setText(
                f"🎛 Активные фильтры: {' + '.join(filters_desc)} | Отмечено: {count}/{len(self.checkboxes)}" if filters_desc else ""
            )
            
            QMessageBox.information(self, "Готово",
                f"Отмечено {count} из {len(self.checkboxes)} каналов\n"
                f"Фильтры: {', '.join(filters_desc) if filters_desc else 'нет'}")
    
    def select_all(self):
        for cb, _ in self.checkboxes:
            cb.setChecked(True)
    
    def deselect_all(self):
        for cb, _ in self.checkboxes:
            cb.setChecked(False)
    
    def save_selected_to_database(self):
        if not self.results:
            QMessageBox.warning(self, "Ошибка", "Нет результатов для сохранения!")
            return
        
        selected = [res for cb, res in self.checkboxes if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Не выбрано ни одного канала!")
            return
        
        name, ok = QInputDialog.getText(self, "💾 Сохранить базу", "Введите название базы данных:")
        if ok and name:
            channels_data = []
            for res in selected:
                channels_data.append({
                    "name": f"@{res['username']}",
                    "link": f"https://t.me/{res['username']}",
                    "subscribers": 0,
                    "can_comment": res['can_comment'],
                    "language": res.get('language', 'unknown')
                })
            
            db_data = {
                "name": name,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "channels": channels_data
            }
            self.main.databases.append(db_data)
            self.main.save_databases()
            self.main.databases_tab.refresh_list()
            
            QMessageBox.information(self, "✅ Готово", f"Сохранено {len(selected)} каналов в базу '{name}'")
    
    def export_selected(self):
        if not self.results:
            QMessageBox.warning(self, "Ошибка", "Нет результатов для экспорта!")
            return
        
        selected = [res for cb, res in self.checkboxes if cb.isChecked()]
        if not selected:
            QMessageBox.warning(self, "Ошибка", "Не выбрано ни одного канала!")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(self, "Экспорт выбранных каналов", "channels.txt", "Text Files (*.txt)")
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    for res in selected:
                        f.write(f"@{res['username']}\n")
                QMessageBox.information(self, "✅ Готово", f"Сохранено {len(selected)} юзернеймов в {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {str(e)}")
    
    def clear_results(self):
        if self.results and QMessageBox.question(self, "Очистка", "Очистить все результаты?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
            self.results = []
            self.checkboxes = []
            self.results_table.setRowCount(0)
            self.active_filter_state = {"only_comments": False, "selected_langs": None}
            self.active_filters_label.setText("")
            self.log_text.clear()
            self.log_signal.emit("🧹 Результаты очищены")

# ========== ВКЛАДКА БАЗ ==========
class DatabasesTab(QWidget):
    refresh_signal = pyqtSignal()
    
    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setup_ui()
        self.refresh_signal.connect(self.refresh_list)
    
    def setup_ui(self):
        layout = QVBoxLayout()
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("➕ Добавить базу")
        self.add_btn.clicked.connect(self.add_database)
        self.split_btn = QPushButton("✂️ Разбить базу")
        self.split_btn.clicked.connect(self.split_database)
        self.remove_btn = QPushButton("🗑 Удалить")
        self.remove_btn.clicked.connect(self.remove_database)
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.split_btn)
        btn_layout.addWidget(self.remove_btn)
        layout.addLayout(btn_layout)

        io_layout = QHBoxLayout()
        self.export_btn = QPushButton("📤 Экспорт базы")
        self.export_btn.clicked.connect(self.export_database)
        self.export_btn.setStyleSheet("background-color: #a6e3a1; color: #1e1e2e;")
        self.import_btn = QPushButton("📥 Импорт базы")
        self.import_btn.clicked.connect(self.import_database)
        self.import_btn.setStyleSheet("background-color: #f9e2af; color: #1e1e2e;")
        self.export_all_btn = QPushButton("📦 Экспорт всех баз")
        self.export_all_btn.clicked.connect(self.export_all_databases)
        self.export_all_btn.setStyleSheet("background-color: #89b4fa; color: #1e1e2e;")
        io_layout.addWidget(self.export_btn)
        io_layout.addWidget(self.import_btn)
        io_layout.addWidget(self.export_all_btn)
        layout.addLayout(io_layout)
        
        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)
        
        self.setLayout(layout)
        self.refresh_list()
    
    @pyqtSlot()
    def refresh_list(self):
        self.list_widget.clear()
        for db in self.main.databases:
            cnt = len(db.get('channels', []))
            item = QListWidgetItem(f"📁 {db['name']} - {cnt} каналов ({db.get('date', '')})")
            item.setData(Qt.UserRole, db)
            self.list_widget.addItem(item)
    
    def add_database(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выбрать файл", "", "Text Files (*.txt)")
        if path:
            name, ok = QInputDialog.getText(self, "Название", "Введите название:")
            if ok and name:
                channels = []
                with open(path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            clean_name = line.replace("https://t.me/", "").replace("@", "")
                            channels.append({
                                "name": f"@{clean_name}",
                                "link": f"https://t.me/{clean_name}",
                                "subscribers": 0
                            })
                self.main.databases.append({"name": name, "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "channels": channels})
                self.main.save_databases()
                self.refresh_list()
                QMessageBox.information(self, "Готово", f"Добавлено {len(channels)} каналов")
    
    def split_database(self):
        current = self.list_widget.currentItem()
        if not current:
            QMessageBox.warning(self, "Ошибка", "Выберите базу!")
            return
        db = current.data(Qt.UserRole)
        channels = db.get('channels', [])
        if not channels:
            QMessageBox.warning(self, "Ошибка", "Нет каналов!")
            return
        size, ok = QInputDialog.getInt(self, "Разбиение", f"В базе {len(channels)} каналов.\nСколько в каждой?", 50, 1, len(channels))
        if not ok:
            return
        num = (len(channels) + size - 1) // size
        for i in range(num):
            start = i * size
            end = min((i + 1) * size, len(channels))
            self.main.databases.append({
                "name": f"{db['name']}_part{i+1}",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "channels": channels[start:end]
            })
        self.main.save_databases()
        self.refresh_list()
        QMessageBox.information(self, "Готово", f"Разбито на {num} частей")
    
    def remove_database(self):
        current = self.list_widget.currentItem()
        if current:
            db = current.data(Qt.UserRole)
            if QMessageBox.question(self, "Удаление", f"Удалить '{db['name']}'?", QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self.main.databases = [d for d in self.main.databases if d != db]
                self.main.save_databases()
                self.refresh_list()

    def export_database(self):
        current = self.list_widget.currentItem()
        if not current:
            QMessageBox.warning(self, "Ошибка", "Выберите базу для экспорта!")
            return
        db = current.data(Qt.UserRole)
        default_name = f"{db['name'].replace(' ', '_')}.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт базы", default_name,
            "JSON Files (*.json);;Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            try:
                if file_path.endswith('.txt'):
                    with open(file_path, 'w', encoding='utf-8') as f:
                        for ch in db.get('channels', []):
                            f.write(f"{ch.get('name', '')}\n")
                else:
                    export_data = {
                        "format": "tg_channel_db",
                        "version": VERSION,
                        "exported": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "database": db
                    }
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(export_data, f, ensure_ascii=False, indent=2)
                QMessageBox.information(self, "Готово",
                    f"База '{db['name']}' экспортирована!\n"
                    f"Каналов: {len(db.get('channels', []))}\n"
                    f"Файл: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {str(e)}")

    def import_database(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Импорт базы", "",
            "JSON Files (*.json);;Text Files (*.txt);;All Files (*)"
        )
        if not file_path:
            return
        try:
            if file_path.endswith('.txt'):
                channels = []
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            clean_name = line.replace("https://t.me/", "").replace("@", "")
                            channels.append({
                                "name": f"@{clean_name}",
                                "link": f"https://t.me/{clean_name}",
                                "subscribers": 0
                            })
                if not channels:
                    QMessageBox.warning(self, "Ошибка", "Файл пуст или не содержит каналов!")
                    return
                name, ok = QInputDialog.getText(self, "Название", "Введите название для импортированной базы:")
                if not ok or not name:
                    return
                db_data = {
                    "name": name,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "channels": channels
                }
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                if isinstance(data, dict) and "databases" in data:
                    dbs_to_import = data["databases"]
                    imported_count = 0
                    total_channels = 0
                    existing_names = [d['name'] for d in self.main.databases]
                    for db_item in dbs_to_import:
                        if "date" not in db_item:
                            db_item["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if db_item.get('name', '') in existing_names:
                            db_item['name'] = f"{db_item['name']}_imported"
                        existing_names.append(db_item['name'])
                        self.main.databases.append(db_item)
                        imported_count += 1
                        total_channels += len(db_item.get('channels', []))
                    self.main.save_databases()
                    self.refresh_list()
                    QMessageBox.information(self, "Готово",
                        f"Импортировано {imported_count} баз\nВсего каналов: {total_channels}")
                    return
                elif isinstance(data, dict) and "database" in data:
                    db_data = data["database"]
                elif isinstance(data, dict) and "name" in data and "channels" in data:
                    db_data = data
                elif isinstance(data, list):
                    name, ok = QInputDialog.getText(self, "Название", "Введите название для импортированной базы:")
                    if not ok or not name:
                        return
                    db_data = {
                        "name": name,
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "channels": data
                    }
                else:
                    QMessageBox.warning(self, "Ошибка", "Неизвестный формат JSON файла!")
                    return

                if "date" not in db_data:
                    db_data["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            existing_names = [d['name'] for d in self.main.databases]
            original_name = db_data['name']
            if original_name in existing_names:
                rename, ok = QInputDialog.getText(
                    self, "Конфликт имён",
                    f"База с именем '{original_name}' уже существует.\nВведите новое имя:",
                    QLineEdit.Normal, f"{original_name}_imported"
                )
                if ok and rename:
                    db_data['name'] = rename
                else:
                    return

            self.main.databases.append(db_data)
            self.main.save_databases()
            self.refresh_list()
            channels_count = len(db_data.get('channels', []))
            QMessageBox.information(self, "Готово",
                f"База '{db_data['name']}' импортирована!\nКаналов: {channels_count}")

        except json.JSONDecodeError:
            QMessageBox.critical(self, "Ошибка", "Файл содержит невалидный JSON!")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка импорта: {str(e)}")

    def export_all_databases(self):
        if not self.main.databases:
            QMessageBox.warning(self, "Ошибка", "Нет баз для экспорта!")
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт всех баз", "all_databases.json",
            "JSON Files (*.json);;All Files (*)"
        )
        if file_path:
            try:
                export_data = {
                    "format": "tg_channel_db_pack",
                    "version": VERSION,
                    "exported": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "count": len(self.main.databases),
                    "databases": self.main.databases
                }
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, ensure_ascii=False, indent=2)
                total_channels = sum(len(d.get('channels', [])) for d in self.main.databases)
                QMessageBox.information(self, "Готово",
                    f"Экспортировано {len(self.main.databases)} баз\n"
                    f"Всего каналов: {total_channels}\n"
                    f"Файл: {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Ошибка экспорта: {str(e)}")

# ========== ЗАПУСК ==========
def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setStyleSheet("""
        QMainWindow, QWidget { background-color: #1e1e2e; color: #cdd6f4; }
        QTableWidget { background-color: #181825; gridline-color: #313244; }
        QHeaderView::section { background-color: #313244; padding: 5px; }
        QPushButton { background-color: #89b4fa; color: #1e1e2e; border: none; padding: 8px 15px; border-radius: 6px; font-weight: bold; }
        QPushButton:hover { background-color: #b4befe; }
        QLineEdit, QTextEdit, QComboBox, QSpinBox { background-color: #181825; border: 1px solid #313244; border-radius: 6px; padding: 6px; }
        QTabBar::tab { background-color: #181825; padding: 8px 16px; }
        QTabBar::tab:selected { background-color: #89b4fa; color: #1e1e2e; }
        QCheckBox { spacing: 8px; }
        QGroupBox { border: 1px solid #313244; border-radius: 8px; margin-top: 10px; padding-top: 10px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        QScrollArea { border: none; background-color: transparent; }
        QScrollBar:vertical { background-color: #181825; width: 12px; border-radius: 6px; }
        QScrollBar::handle:vertical { background-color: #89b4fa; border-radius: 6px; min-height: 30px; }
        QScrollBar::handle:vertical:hover { background-color: #b4befe; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; height: 0px; }
    """)
    
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()