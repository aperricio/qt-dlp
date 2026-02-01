#!/usr/bin/env python3
import sys
import subprocess
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout, QLabel, QButtonGroup, QFrame,
    QScrollArea, QGroupBox, QMessageBox,
    QDialog, QVBoxLayout, QComboBox, QDialogButtonBox, QRadioButton,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSettings
from PyQt6.QtGui import QFont, QPalette, QColor, QAction, QIcon

# ==================== CONFIGURACIÓN ====================
class AppConfig:
    def __init__(self):
        self.settings = QSettings("qt-dlp", "Config")
    
    def get_preferred_browser(self):
        return self.settings.value("preferred_browser", "firefox", type=str)
    
    def set_preferred_browser(self, browser):
        self.settings.setValue("preferred_browser", browser)
    
    def get_formats_layout(self):
        """Diseño de formatos: 'single_column', 'two_columns'"""
        return self.settings.value("formats_layout", "two_columns", type=str)
    
    def set_formats_layout(self, layout):
        self.settings.setValue("formats_layout", layout)

# ==================== HILOS ====================
class DownloadThread(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    retry_with_cookies = pyqtSignal()

    def __init__(self, url, format_spec=None, use_cookies=False, browser="firefox"):
        super().__init__()
        self.url = url
        self.format_spec = format_spec
        self.use_cookies = use_cookies
        self.browser = browser
        self._terminated = False

    def run(self):
        try:
            # Construir comando base
            if self.format_spec:
                cmd = ["yt-dlp", "-f", self.format_spec, self.url]
            else:
                cmd = ["yt-dlp", self.url]
            
            # Añadir cookies si se requieren
            if self.use_cookies and self.browser != "none":
                cmd.insert(1, "--cookies-from-browser")
                cmd.insert(2, self.browser)
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding='utf-8',
                errors='replace'
            )
            
            output_lines = []
            for line in process.stdout:
                if self._terminated:
                    process.terminate()
                    self.error.emit("Descarga cancelada")
                    return
                if line.strip():
                    self.progress.emit(line.strip())
                    output_lines.append(line.strip())
            
            process.wait()
            
            # Verificar si hubo errores
            if process.returncode != 0:
                error_output = "\n".join(output_lines[-5:])
                
                # Determinar el tipo de error
                error_lower = error_output.lower()
                
                # Verificar restricción de edad
                age_indicators = [
                    "sign in to confirm your age",
                    "age verification",
                    "age-restricted",
                    "confirm your age",
                    "this video may be inappropriate",
                    "restricted",
                    "age check"
                ]
                
                has_age_restriction = any(indicator in error_lower for indicator in age_indicators)
                
                if has_age_restriction and not self.use_cookies:
                    # Contenido con restricción de edad sin cookies
                    self.retry_with_cookies.emit()
                else:
                    # Otro tipo de error
                    self.error.emit(f"Error en la descarga: {error_output}")
            else:
                self.finished.emit()
                
        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        self._terminated = True

class FormatsThread(QThread):
    formats_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, url, use_cookies=False, browser="firefox"):
        super().__init__()
        self.url = url
        self.use_cookies = use_cookies
        self.browser = browser

    def run(self):
        try:
            # Estrategia: intentar primero sin cookies, luego con cookies si falla
            result = None
            
            # Primero intentar sin cookies (más rápido y privado)
            cmd = ["yt-dlp", "--dump-single-json", self.url]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=30
            )
            
            # Si falla y el error indica restricción de edad, intentar con cookies
            if result.returncode != 0:
                error_lower = result.stderr.lower()
                age_indicators = [
                    "sign in to confirm your age",
                    "age verification",
                    "age-restricted",
                    "confirm your age",
                    "this video may be inappropriate"
                ]
                
                has_age_restriction = any(indicator in error_lower for indicator in age_indicators)
                
                if has_age_restriction and self.browser != "none":
                    # Reintentar con cookies
                    retry_cmd = ["yt-dlp", "--dump-single-json", "--cookies-from-browser", self.browser, self.url]
                    
                    result = subprocess.run(
                        retry_cmd,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        timeout=30
                    )
            
            if result.returncode == 0:
                info = json.loads(result.stdout)
                formats = self.process_formats(info)
                self.formats_ready.emit(formats)
            else:
                self.error.emit(f"Error obteniendo formatos: {result.stderr[:200]}...")
                        
        except subprocess.TimeoutExpired:
            self.error.emit("Tiempo de espera agotado")
        except Exception as e:
            self.error.emit(f"Error: {str(e)}")

    def process_formats(self, info):
        """Procesa los formatos obtenidos de yt-dlp"""
        title = info.get("title", "Contenido sin título")
        age_limit = info.get("age_limit", 0)  # 0 = sin restricción
        requires_cookies = age_limit > 0
        
        formats = {
            "title": title,
            "age_limit": age_limit,
            "requires_cookies": requires_cookies,
            "video": [],
            "audio": []
        }
        
        for f in info.get("formats", []):
            fmt_id = f.get("format_id", "N/A")
            ext = f.get("ext", "")
            quality = f.get("height", "")
            fps = f.get("fps", "")
            vcodec = f.get("vcodec", "none")
            acodec = f.get("acodec", "none")
            filesize = f.get("filesize", f.get("filesize_approx", 0))
            
            if filesize:
                size_mb = filesize / (1024*1024)
                if size_mb < 1024:
                    size_str = f"{size_mb:.1f} MB"
                else:
                    size_str = f"{size_mb/1024:.1f} GB"
            else:
                size_str = "Tamaño estimado"
            
            # Solo formatos separados
            if vcodec != "none" and acodec == "none":
                desc_parts = []
                if quality:
                    desc_parts.append(f"{quality}p")
                if fps and fps > 0:
                    desc_parts.append(f"{int(fps)}fps")
                if ext:
                    desc_parts.append(f".{ext}")
                if vcodec != "none" and vcodec != "av01":
                    codec_short = vcodec.split('.')[0][:10]
                    desc_parts.append(codec_short)
                
                desc = " ".join(desc_parts)
                formats["video"].append({
                    "id": fmt_id,
                    "desc": f"🎥 {desc}\n   📊 {size_str}",
                    "quality": quality or 0,
                    "type": "video",
                    "size_str": size_str
                })
                
            elif vcodec == "none" and acodec != "none":
                bitrate = f.get("abr", 0)
                codec_short = acodec.split('.')[0][:10] if acodec != "none" else ""
                desc = f"🔊 {bitrate}kbps .{ext} {codec_short}\n   📊 {size_str}"
                formats["audio"].append({
                    "id": fmt_id,
                    "desc": desc,
                    "quality": bitrate,
                    "type": "audio",
                    "size_str": size_str
                })
        
        # Ordenar y limitar a las mejores calidades
        formats["video"].sort(key=lambda x: x["quality"], reverse=True)
        formats["audio"].sort(key=lambda x: x["quality"], reverse=True)
        
        # Mostrar solo las 10 mejores calidades de cada tipo
        formats["video"] = formats["video"][:10]
        formats["audio"] = formats["audio"][:5]
        
        return formats

# ==================== DIÁLOGO DE CONFIGURACIÓN ====================
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Configuración de qt-dlp")
        self.setMinimumWidth(450)
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Navegador para cookies
        browser_group = QGroupBox("Navegador para cookies")
        browser_layout = QVBoxLayout()
        
        self.browser_combo = QComboBox()
        self.browser_combo.addItems([
            "firefox", "chrome", "chromium", "edge", "brave", 
            "opera", "vivaldi", "librewolf", "tor", "none"
        ])
        self.browser_combo.setCurrentText(self.config.get_preferred_browser())
        browser_layout.addWidget(self.browser_combo)
        
        browser_note = QLabel(
            "Selecciona el navegador del que obtener las cookies.\n"
            "La app primero intentará sin cookies. Si falla por restricción de edad,\n"
            "usará cookies de este navegador. 'none' = nunca usar cookies."
        )
        browser_note.setStyleSheet("color: #888; font-size: 9px;")
        browser_note.setWordWrap(True)
        browser_layout.addWidget(browser_note)
        
        browser_group.setLayout(browser_layout)
        layout.addWidget(browser_group)
        
        # Diseño de formatos
        layout_group = QGroupBox("Diseño de la interfaz")
        layout_layout = QVBoxLayout()
        
        self.layout_single = QRadioButton("📋 Lista única (todos los formatos en una columna)")
        self.layout_two = QRadioButton("📊 Dos columnas (vídeo a la izquierda, audio a la derecha)")
        
        # Agrupar para que sean excluyentes
        self.layout_button_group = QButtonGroup()
        self.layout_button_group.addButton(self.layout_single)
        self.layout_button_group.addButton(self.layout_two)
        
        current_layout = self.config.get_formats_layout()
        if current_layout == "single_column":
            self.layout_single.setChecked(True)
        else:
            self.layout_two.setChecked(True)
        
        layout_layout.addWidget(self.layout_single)
        layout_layout.addWidget(self.layout_two)
        layout_group.setLayout(layout_layout)
        layout.addWidget(layout_group)
        
        # Botones
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        self.setLayout(layout)
    
    def accept(self):
        # Guardar configuración
        self.config.set_preferred_browser(self.browser_combo.currentText())
        
        if self.layout_single.isChecked():
            self.config.set_formats_layout("single_column")
        else:
            self.config.set_formats_layout("two_columns")
        
        super().accept()

# ==================== VENTANA PRINCIPAL ====================
class QtDLP(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("qt-dlp")
        # Reducir el tamaño mínimo inicial
        self.setMinimumSize(800, 400)  # Reducido de 1000x760
        self.setWindowIcon(QIcon("img/qt-dlp.png"))
        
        # Variables
        self.config = AppConfig()
        self.download_thread = None
        self.formats_thread = None
        self.current_download_url = None
        self.current_format_spec = None
        self.current_theme = "dark"
        self.formats_loaded = False
        self.video_buttons = []
        self.audio_buttons = []
        self.current_age_limit = 0
        self.requires_cookies = False
        
        # Crear menú
        self.create_menu()
        
        # Crear UI
        self.init_ui()
        
        # Aplicar tema
        self.apply_theme(self.current_theme)
        
    def create_menu(self):
        menubar = self.menuBar()
        
        # Menú Archivo
        file_menu = menubar.addMenu("Archivo")
        file_menu.addAction(QAction("Configuración...", self, triggered=self.show_settings))
        file_menu.addSeparator()
        file_menu.addAction(QAction("Salir", self, triggered=self.close))
        
        # Menú Tema
        theme_menu = menubar.addMenu("Tema")
        theme_menu.addAction(QAction("🌞 Tema Claro", self, triggered=lambda: self.apply_theme("light")))
        theme_menu.addAction(QAction("🌙 Tema Oscuro", self, triggered=lambda: self.apply_theme("dark")))
        
        # Menú Ayuda
        help_menu = menubar.addMenu("Ayuda")
        help_menu.addAction(QAction("Acerca de", self, triggered=self.show_about))
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Sección URL - Altura fija
        url_frame = QFrame()
        url_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        url_frame.setMinimumHeight(120)
        url_frame.setMaximumHeight(140)
        url_layout = QVBoxLayout(url_frame)
        url_layout.setSpacing(8)
        
        url_label = QLabel("URL del contenido:")
        url_label.setContentsMargins(8, 8, 8, 8)  # Izquierda, Arriba, Derecha, Abajo

        url_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        url_layout.addWidget(url_label)
        
        url_input_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Pega el enlace aquí (YouTube, Twitch, Twitter/X, TikTok, Instagram, etc)...")
        self.url_input.setMinimumHeight(40)
        self.url_input.returnPressed.connect(self.download_direct)
        url_input_layout.addWidget(self.url_input)
        
        url_buttons_layout = QHBoxLayout()
        self.download_direct_btn = QPushButton("⬇ Descarga Directa")
        self.download_direct_btn.setMinimumHeight(40)
        self.download_direct_btn.setMinimumWidth(180)
        self.download_direct_btn.setToolTip("Descarga el mejor vídeo y audio combinados")
        
        self.fetch_formats_btn = QPushButton("📋 Ver Formatos")
        self.fetch_formats_btn.setMinimumHeight(40)
        self.fetch_formats_btn.setMinimumWidth(150)
        self.fetch_formats_btn.setToolTip("Muestra formatos disponibles para seleccionar")
        
        self.clear_btn = QPushButton("🗑️ Limpiar")
        self.clear_btn.setMinimumHeight(40)
        self.clear_btn.setMinimumWidth(120)
        
        url_buttons_layout.addWidget(self.download_direct_btn)
        url_buttons_layout.addWidget(self.fetch_formats_btn)
        url_buttons_layout.addWidget(self.clear_btn)
        url_buttons_layout.addStretch()
        
        url_layout.addLayout(url_input_layout)
        url_layout.addLayout(url_buttons_layout)
        main_layout.addWidget(url_frame)
        
        # Información del contenido (inicialmente oculta) - Altura variable según contenido
        self.content_info_frame = QFrame()
        self.content_info_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.content_info_frame.setVisible(False)  # Oculto inicialmente
        self.content_info_frame.setMinimumHeight(40)
        self.content_info_frame.setMaximumHeight(80)
        content_info_layout = QVBoxLayout(self.content_info_frame)
        content_info_layout.setContentsMargins(12, 8, 12, 8)
        
        self.content_info_label = QLabel("")
        self.content_info_label.setFont(QFont("Arial", 9))
        self.content_info_label.setWordWrap(True)
        content_info_layout.addWidget(self.content_info_label)
        
        main_layout.addWidget(self.content_info_frame)
        
        # Sección de formatos - Inicialmente oculta - Se expandirá
        self.formats_frame = QFrame()
        self.formats_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.formats_frame.setVisible(False)  # Oculto inicialmente
        self.formats_layout = QVBoxLayout(self.formats_frame)
        self.formats_layout.setContentsMargins(12, 12, 12, 12)
        
        formats_label = QLabel("Formatos Disponibles (selecciona uno de cada tipo):")
        formats_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        self.formats_layout.addWidget(formats_label)
        
        # Contenedor principal para formatos (se llenará dinámicamente)
        self.formats_container = QWidget()
        self.formats_container_layout = QVBoxLayout(self.formats_container)
        self.formats_layout.addWidget(self.formats_container, 1)  # Factor de expansión 1
        
        main_layout.addWidget(self.formats_frame, 1)  # Este frame se expandirá
        
        # Botón de descarga con selección (inicialmente oculto) - Altura fija
        self.download_with_selection_btn = QPushButton("⬇ DESCARGAR SELECCIÓN")
        self.download_with_selection_btn.setMinimumHeight(50)
        self.download_with_selection_btn.setMinimumWidth(250)
        self.download_with_selection_btn.setVisible(False)
        main_layout.addWidget(self.download_with_selection_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        # Botones de control - Altura fija
        controls_frame = QFrame()
        controls_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        controls_frame.setMinimumHeight(70)
        controls_frame.setMaximumHeight(80)
        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(12, 8, 12, 8)
        
        self.cancel_btn = QPushButton("❌ CANCELAR")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.setMinimumWidth(150)
        self.cancel_btn.setEnabled(False)
        
        controls_layout.addWidget(self.cancel_btn)
        controls_layout.addStretch()
        
        self.status_label = QLabel("💤 Listo")
        self.status_label.setFont(QFont("Arial", 9))
        self.status_label.setContentsMargins(8, 8, 8, 8)
        self.status_label.setMinimumWidth(200)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        controls_layout.addWidget(self.status_label)
        
        main_layout.addWidget(controls_frame)
        
        # Conectar señales
        self.download_direct_btn.clicked.connect(self.download_direct)
        self.fetch_formats_btn.clicked.connect(self.fetch_formats)
        self.cancel_btn.clicked.connect(self.cancel_operation)
        self.clear_btn.clicked.connect(self.clear_all)
        self.download_with_selection_btn.clicked.connect(self.download_with_selection)
    
    def apply_theme(self, theme):
        self.current_theme = theme
        
        if theme == "dark":
            dark_palette = QPalette()
            dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
            dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
            dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
            dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
            dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
            dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
            dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
            dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            
            QApplication.instance().setPalette(dark_palette)
            
            style = """
                QMainWindow { 
                    background-color: #2b2b2b; 
                }
                QFrame { 
                    background-color: #353535; 
                    border-radius: 8px; 
                    border: 1px solid #444444;
                }
                QLabel { 
                    color: #ffffff; 
                }
                QLineEdit { 
                    background-color: #454545; 
                    color: white; 
                    border: 2px solid #555555; 
                    border-radius: 6px; 
                    padding: 8px;
                    font-size: 14px;
                }
                QLineEdit:focus { 
                    border: 2px solid #2a82da;
                    background-color: #505050;
                }
                QPushButton { 
                    background-color: #4a4a4a; 
                    color: white; 
                    border: none; 
                    border-radius: 6px; 
                    padding: 10px 16px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover { 
                    background-color: #5a5a5a;
                    border: 1px solid #666666;
                }
                QPushButton:pressed { 
                    background-color: #3a3a3a;
                }
                QPushButton:checked { 
                    background-color: #2a82da;
                    color: white;
                }
                QPushButton:disabled { 
                    background-color: #333333;
                    color: #777777;
                }
                QScrollArea { 
                    border: 1px solid #444444;
                    border-radius: 6px;
                    background: #2b2b2b;
                }
                QScrollBar:vertical {
                    background: #3a3a3a;
                    width: 14px;
                    border-radius: 7px;
                }
                QScrollBar::handle:vertical {
                    background: #5a5a5a;
                    border-radius: 7px;
                    min-height: 30px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #6a6a6a;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #444444;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 12px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 8px 0 8px;
                }
            """
        else:
            QApplication.instance().setPalette(QApplication.instance().style().standardPalette())
            
            style = """
                QMainWindow { 
                    background-color: #f5f5f5; 
                }
                QFrame { 
                    background-color: white; 
                    border-radius: 8px; 
                    border: 1px solid #dddddd;
                }
                QLabel { 
                    color: #333333; 
                }
                QLineEdit { 
                    background-color: white; 
                    color: black; 
                    border: 2px solid #cccccc; 
                    border-radius: 6px; 
                    padding: 8px;
                    font-size: 14px;
                }
                QLineEdit:focus { 
                    border: 2px solid #2a82da;
                    background-color: #f9f9f9;
                }
                QPushButton { 
                    background-color: #f0f0f0; 
                    color: #333333; 
                    border: 1px solid #cccccc; 
                    border-radius: 6px; 
                    padding: 10px 16px;
                    font-weight: bold;
                    font-size: 13px;
                }
                QPushButton:hover { 
                    background-color: #e0e0e0;
                    border: 1px solid #bbbbbb;
                }
                QPushButton:pressed { 
                    background-color: #d0d0d0;
                }
                QPushButton:checked { 
                    background-color: #2a82da;
                    color: white;
                    border: 1px solid #1a72ca;
                }
                QPushButton:disabled { 
                    background-color: #f9f9f9;
                    color: #aaaaaa;
                }
                QScrollArea { 
                    border: 1px solid #dddddd;
                    border-radius: 6px;
                    background: white;
                }
                QScrollBar:vertical {
                    background: #f0f0f0;
                    width: 14px;
                    border-radius: 7px;
                }
                QScrollBar::handle:vertical {
                    background: #c0c0c0;
                    border-radius: 7px;
                    min-height: 30px;
                }
                QScrollBar::handle:vertical:hover {
                    background: #a0a0a0;
                }
                QGroupBox {
                    font-weight: bold;
                    border: 2px solid #dddddd;
                    border-radius: 8px;
                    margin-top: 12px;
                    padding-top: 12px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 12px;
                    padding: 0 8px 0 8px;
                }
            """
        
        QApplication.instance().setStyleSheet(style)
    
    def show_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            QMessageBox.information(self, "Configuración", "Los cambios se aplicarán en la próxima operación.")
    
    def create_format_button(self, fmt):
        btn = QPushButton(fmt["desc"])
        btn.setCheckable(True)
        btn.format_id = fmt["id"]
        btn.format_type = fmt["type"]
        btn.setMinimumHeight(60)
        btn.setMaximumWidth(350)
        
        # Estilo para botones tipo radio (solo uno seleccionado)
        btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 8px;
                border: 2px solid #555555;
            }
            QPushButton:checked {
                background-color: #2a82da;
                color: white;
                border: 2px solid #1a72ca;
            }
            QPushButton:hover:!checked {
                background-color: #5a5a5a;
                border: 2px solid #666666;
            }
        """)
        
        btn.clicked.connect(lambda checked, b=btn: self.on_format_button_clicked(b, checked))
        return btn
    
    def on_format_button_clicked(self, clicked_button, checked):
        """Maneja clics en botones de formato (comportamiento tipo radio)"""
        if not checked:
            # Si se hace clic en un botón ya seleccionado, mantenerlo seleccionado
            clicked_button.setChecked(True)
            return
            
        # Deseleccionar otros botones del mismo tipo
        if clicked_button.format_type == "video":
            for btn in self.video_buttons:
                if btn != clicked_button:
                    btn.setChecked(False)
        else:
            for btn in self.audio_buttons:
                if btn != clicked_button:
                    btn.setChecked(False)
        
        self.update_download_selection_btn()
    
    def update_download_selection_btn(self):
        has_video = any(btn.isChecked() for btn in self.video_buttons)
        has_audio = any(btn.isChecked() for btn in self.audio_buttons)
        
        if has_video or has_audio:
            self.download_with_selection_btn.setEnabled(True)
        else:
            self.download_with_selection_btn.setEnabled(False)
    
    def clear_formats_container(self):
        """Limpia el contenedor de formatos"""
        # Limpiar listas de botones
        self.video_buttons.clear()
        self.audio_buttons.clear()
        
        # Limpiar layout del contenedor
        while self.formats_container_layout.count():
            item = self.formats_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # Limpiar sub-layouts
                sublayout = item.layout()
                while sublayout.count():
                    subitem = sublayout.takeAt(0)
                    if subitem.widget():
                        subitem.widget().deleteLater()
    
    def clear_formats(self):
        self.clear_formats_container()
        self.hide_content_info()
        self.hide_formats_section()
        self.download_with_selection_btn.setVisible(False)
        self.formats_loaded = False
        self.current_age_limit = 0
        self.requires_cookies = False
        
        # Ajustar tamaño de ventana
        self.resize(800, 400)
    
    def show_content_info(self, title, age_limit, requires_cookies):
        """Muestra la información del contenido"""
        age_info = ""
        if age_limit > 0:
            age_info = f" 🔞 +{age_limit}"
            if requires_cookies:
                age_info += " (requiere cookies)"
        
        self.content_info_label.setText(f"📺 {title}{age_info}")
        self.content_info_frame.setVisible(True)
        
    def hide_content_info(self):
        """Oculta la información del contenido"""
        self.content_info_frame.setVisible(False)
        self.content_info_label.setText("")
    
    def show_formats_section(self):
        """Muestra la sección de formatos"""
        self.formats_frame.setVisible(True)
        
    def hide_formats_section(self):
        """Oculta la sección de formatos"""
        self.formats_frame.setVisible(False)
    
    def download_direct(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Advertencia", "Por favor, introduce una URL")
            return
        
        # Obtener información básica del contenido para mostrar nombre
        try:
            # Comando rápido para obtener solo el título
            cmd = ["yt-dlp", "--get-title", url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                title = result.stdout.strip()
                self.show_content_info(title, 0, False)
        except:
            # Si falla, no mostramos info
            pass
        
        # Ocultar secciones de formatos si estaban visibles
        self.hide_formats_section()
        self.download_with_selection_btn.setVisible(False)
        
        self.start_download(url, None)
    
    def fetch_formats(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Advertencia", "Por favor, introduce una URL")
            return
        
        self.clear_formats()
        self.status_label.setText("⏳ Obteniendo formatos...")
        self.download_direct_btn.setEnabled(False)
        self.fetch_formats_btn.setEnabled(False)
        self.url_input.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        
        # Para obtener formatos, NO usar cookies inicialmente
        # Las cookies solo se usarán si detectamos restricción de edad
        self.formats_thread = FormatsThread(
            url, 
            use_cookies=False,  # Siempre intentar primero sin cookies
            browser=self.config.get_preferred_browser()
        )
        self.formats_thread.formats_ready.connect(self.display_formats)
        self.formats_thread.error.connect(self.show_error)
        self.formats_thread.start()
    
    def display_formats(self, formats):
        self.download_direct_btn.setEnabled(True)
        self.fetch_formats_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        title = formats.get("title", "Contenido sin título")
        self.current_age_limit = formats.get("age_limit", 0)
        self.requires_cookies = formats.get("requires_cookies", False)
        
        # Mostrar información del contenido
        self.show_content_info(title, self.current_age_limit, self.requires_cookies)
        
        if not any([formats["video"], formats["audio"]]):
            self.status_label.setText("❌ No se encontraron formatos separados")
            return
        
        # Obtener el diseño seleccionado
        layout_type = self.config.get_formats_layout()
        
        if layout_type == "two_columns":
            self.display_formats_two_columns(formats)
        else:
            self.display_formats_single_column(formats)
        
        # Mostrar sección de formatos y botón de descarga
        self.show_formats_section()
        self.download_with_selection_btn.setVisible(True)
        self.update_download_selection_btn()
        
        video_count = len(formats['video'])
        audio_count = len(formats['audio'])
        
        if self.requires_cookies:
            self.status_label.setText(f"✅ {video_count} vídeos, {audio_count} audios (requiere cookies)")
        else:
            self.status_label.setText(f"✅ {video_count} vídeos, {audio_count} audios")
        
        self.formats_loaded = True
        # Ajustar tamaño de ventana para mostrar contenido
        self.resize(1000, 760)
    
    def display_formats_two_columns(self, formats):
        """Muestra formatos en dos columnas (video izquierda, audio derecha)"""
        # Crear un layout horizontal principal
        main_horizontal = QHBoxLayout()
        main_horizontal.setSpacing(20)
        
        # Columna de video
        if formats["video"]:
            video_frame = QFrame()
            video_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
            video_layout = QVBoxLayout(video_frame)
            
            video_label = QLabel("🎥 Formatos de Video (selecciona uno):")
            video_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            video_layout.addWidget(video_label)
            
            video_scroll = QScrollArea()
            video_scroll.setWidgetResizable(True)
            video_scroll_content = QWidget()
            video_buttons_layout = QVBoxLayout(video_scroll_content)
            video_buttons_layout.setSpacing(5)
            
            for fmt in formats["video"]:
                btn = self.create_format_button(fmt)
                self.video_buttons.append(btn)
                video_buttons_layout.addWidget(btn)
            
            video_scroll.setWidget(video_scroll_content)
            video_layout.addWidget(video_scroll)
            main_horizontal.addWidget(video_frame, 1)  # Factor de estiramiento 1
        
        # Columna de audio
        if formats["audio"]:
            audio_frame = QFrame()
            audio_frame.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
            audio_layout = QVBoxLayout(audio_frame)
            
            audio_label = QLabel("🔊 Formatos de Audio (selecciona uno):")
            audio_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            audio_layout.addWidget(audio_label)
            
            audio_scroll = QScrollArea()
            audio_scroll.setWidgetResizable(True)
            audio_scroll_content = QWidget()
            audio_buttons_layout = QVBoxLayout(audio_scroll_content)
            audio_buttons_layout.setSpacing(5)
            
            for fmt in formats["audio"]:
                btn = self.create_format_button(fmt)
                self.audio_buttons.append(btn)
                audio_buttons_layout.addWidget(btn)
            
            audio_scroll.setWidget(audio_scroll_content)
            audio_layout.addWidget(audio_scroll)
            main_horizontal.addWidget(audio_frame, 1)  # Factor de estiramiento 1
        
        # Añadir el layout horizontal al contenedor
        self.formats_container_layout.addLayout(main_horizontal)
    
    def display_formats_single_column(self, formats):
        """Muestra formatos en una sola columna"""
        # Frame para todos los formatos
        all_formats_frame = QFrame()
        all_formats_layout = QVBoxLayout(all_formats_frame)
        all_formats_layout.setSpacing(10)
        
        # Sección de video
        if formats["video"]:
            video_label = QLabel("🎥 Formatos de Video:")
            video_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            all_formats_layout.addWidget(video_label)
            
            video_container = QWidget()
            video_layout = QVBoxLayout(video_container)
            video_layout.setSpacing(5)
            
            for fmt in formats["video"]:
                btn = self.create_format_button(fmt)
                self.video_buttons.append(btn)
                video_layout.addWidget(btn)
            
            all_formats_layout.addWidget(video_container)
            all_formats_layout.addSpacing(15)
        
        # Sección de audio
        if formats["audio"]:
            audio_label = QLabel("🔊 Formatos de Audio:")
            audio_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            all_formats_layout.addWidget(audio_label)
            
            audio_container = QWidget()
            audio_layout = QVBoxLayout(audio_container)
            audio_layout.setSpacing(5)
            
            for fmt in formats["audio"]:
                btn = self.create_format_button(fmt)
                self.audio_buttons.append(btn)
                audio_layout.addWidget(btn)
            
            all_formats_layout.addWidget(audio_container)
        
        # Scroll area para la columna única
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(all_formats_frame)
        
        self.formats_container_layout.addWidget(scroll_area)
    
    def download_with_selection(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Advertencia", "Por favor, introduce una URL")
            return
        
        selected_video = None
        selected_audio = None
        
        for btn in self.video_buttons:
            if btn.isChecked():
                selected_video = btn.format_id
                break
        
        for btn in self.audio_buttons:
            if btn.isChecked():
                selected_audio = btn.format_id
                break
        
        format_spec = ""
        if selected_video and selected_audio:
            format_spec = f"{selected_video}+{selected_audio}"
        elif selected_video:
            format_spec = selected_video
        elif selected_audio:
            format_spec = selected_audio
        else:
            QMessageBox.warning(self, "Advertencia", "Por favor, selecciona al menos un formato")
            return
        
        self.start_download(url, format_spec)
    
    def start_download(self, url, format_spec):
        self.current_download_url = url
        self.current_format_spec = format_spec
        
        # Comenzar siempre sin cookies
        self.status_label.setText("⏬ Iniciando descarga (sin cookies)...")
        self.download_direct_btn.setEnabled(False)
        self.fetch_formats_btn.setEnabled(False)
        self.download_with_selection_btn.setEnabled(False)
        self.url_input.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        
        self.download_thread = DownloadThread(
            url=url,
            format_spec=format_spec,
            use_cookies=False,
            browser=self.config.get_preferred_browser()
        )
        
        self.download_thread.progress.connect(self.update_status)
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.error.connect(self.download_error)
        self.download_thread.retry_with_cookies.connect(self.retry_download_with_cookies)
        
        self.download_thread.start()
    
    def retry_download_with_cookies(self):
        """Reintenta la descarga con cookies (para contenido con restricción de edad)"""
        self.status_label.setText("⚠️ Reintentando con cookies (contenido restringido)...")
        
        self.download_thread = DownloadThread(
            url=self.current_download_url,
            format_spec=self.current_format_spec,
            use_cookies=True,
            browser=self.config.get_preferred_browser()
        )
        
        self.download_thread.progress.connect(self.update_status)
        self.download_thread.finished.connect(self.download_finished)
        self.download_thread.error.connect(self.download_error)
        
        self.download_thread.start()
    
    def update_status(self, message):
        if any(keyword in message.lower() for keyword in ["download", "eta", "merged", "100%", "already", "of", "at", "in"]):
            # Mostrar mensajes de progreso más cortos
            short_msg = message[:70] + "..." if len(message) > 70 else message
            self.status_label.setText(f"⏬ {short_msg}")
    
    def download_finished(self):
        self.status_label.setText("✅ ¡Descarga completada!")
        self.reset_ui_after_download()
        
        reply = QMessageBox.question(
            self, "Descarga completada",
            "¡Descarga completada con éxito!\n\n¿Deseas descargar otro contenido?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_all()
    
    def download_error(self, message):
        error_lower = message.lower()
        
        # Verificar si es un error de cookies
        cookie_error_indicators = [
            "cookies are missing",
            "cookies invalid", 
            "failed to import cookies",
            "no cookies found",
            "cookies from browser",
            "cannot extract cookie",
            "cookie error",
            "extract cookie"
        ]
        
        is_cookie_error = any(indicator in error_lower for indicator in cookie_error_indicators)
        
        # Si es un error de cookies
        if is_cookie_error:
            QMessageBox.warning(
                self, "Error con cookies",
                "Las cookies no funcionaron correctamente.\n\n"
                "Posibles causas:\n"
                "1. El navegador no está instalado\n"
                "2. No has iniciado sesión en el navegador seleccionado\n"
                "3. Las cookies están bloqueadas\n"
                "4. El navegador está cerrado o en modo privado\n\n"
                "Solución: Selecciona 'none' en Configuración para no usar cookies,\n"
                "o asegúrate de haber iniciado sesión en YouTube con el navegador seleccionado."
            )
        else:
            # Error genérico
            QMessageBox.critical(self, "Error de descarga", message[:500])
        
        self.reset_ui_after_download()
    
    def show_error(self, message):
        QMessageBox.critical(self, "Error", message)
        
        self.status_label.setText("❌ Error en la operación")
        self.reset_ui_after_download()
    
    def reset_ui_after_download(self):
        self.download_direct_btn.setEnabled(True)
        self.fetch_formats_btn.setEnabled(True)
        self.url_input.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        
        if self.formats_loaded:
            self.download_with_selection_btn.setEnabled(True)
    
    def cancel_operation(self):
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.cancel()
            self.download_thread.wait(1000)
        if self.formats_thread and self.formats_thread.isRunning():
            self.formats_thread.terminate()
            self.formats_thread.wait(1000)
        
        self.status_label.setText("⏹️ Operación cancelada")
        self.reset_ui_after_download()
    
    def clear_all(self):
        self.url_input.clear()
        self.status_label.setText("💤 Listo")
        self.clear_formats()
        self.cancel_operation()
    
    def show_about(self):
        QMessageBox.information(
            self, "Acerca de qt-dlp",
            "qt-dlp - Interfaz gráfica para yt-dlp\n\n"
            "Versión 2.4\n\n"
            "Características:\n"
            "• Dos diseños de interfaz (columna única/dos columnas)\n"
            "• Detección automática de contenido restringido\n"
            "• Temas claro/oscuro\n\n"
            "Funcionamiento:\n"
            "1. Primero intenta sin cookies (más rápido y privado)\n"
            "2. Si falla por restricción de edad, usa cookies automáticamente\n"
            "3. Selecciona el navegador en Configuración → Navegador para cookies\n\n"
            "¡Disfruta descargando!"
        )

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    
    window = QtDLP()
    window.show()
    sys.exit(app.exec())
