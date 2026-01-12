"""
PGVectorRAGIndexer Windows Installer - GUI
A modern, polished Tkinter-based installer with progress display.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
import os

# Add parent directory for imports when running from source
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from installer_logic import Installer, InstallStep


# Modern color scheme
COLORS = {
    'bg_dark': '#1a1a2e',
    'bg_medium': '#16213e',
    'bg_light': '#0f3460',
    'accent': '#e94560',
    'accent_green': '#00d4aa',
    'accent_blue': '#667eea',
    'text_primary': '#ffffff',
    'text_secondary': '#a0a0b8',
    'text_muted': '#6c6c8a',
    'success': '#00d4aa',
    'warning': '#ffc107',
    'error': '#e94560',
}


class InstallerGUI:
    """Main installer GUI window with modern styling."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PGVectorRAGIndexer Setup")
        self.root.geometry("520x480")
        self.root.resizable(False, False)
        self.root.configure(bg=COLORS['bg_dark'])
        
        # Center window on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 520) // 2
        y = (self.root.winfo_screenheight() - 480) // 2
        self.root.geometry(f"520x480+{x}+{y}")
        
        # Set icon if available
        try:
            self.root.iconbitmap("icon.ico")
        except:
            pass
        
        self.installer = Installer()
        self.current_step = 0
        self.total_steps = len(self.installer.steps)
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create all GUI widgets with modern styling."""
        # Main container with dark background
        main_frame = tk.Frame(self.root, bg=COLORS['bg_dark'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=20)
        
        # ===== Header with gradient-like effect =====
        header_frame = tk.Frame(main_frame, bg=COLORS['bg_dark'])
        header_frame.pack(fill=tk.X, pady=(0, 25))
        
        # Logo emoji
        logo = tk.Label(
            header_frame,
            text="🔍",
            font=("Segoe UI Emoji", 36),
            bg=COLORS['bg_dark'],
            fg=COLORS['text_primary']
        )
        logo.pack()
        
        # Title with gradient text effect (simulated)
        title = tk.Label(
            header_frame, 
            text="PGVectorRAGIndexer",
            font=("Segoe UI", 22, "bold"),
            bg=COLORS['bg_dark'],
            fg=COLORS['accent_blue']
        )
        title.pack(pady=(5, 0))
        
        subtitle = tk.Label(
            header_frame,
            text="One-Click Installer",
            font=("Segoe UI", 11),
            bg=COLORS['bg_dark'],
            fg=COLORS['text_secondary']
        )
        subtitle.pack(pady=(2, 0))
        
        # ===== Progress Section =====
        progress_section = tk.Frame(main_frame, bg=COLORS['bg_medium'], highlightbackground=COLORS['bg_light'], highlightthickness=1)
        progress_section.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        progress_inner = tk.Frame(progress_section, bg=COLORS['bg_medium'])
        progress_inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)
        
        # Current step label
        self.step_label = tk.Label(
            progress_inner,
            text="Click 'Install' to begin",
            font=("Segoe UI", 11, "bold"),
            bg=COLORS['bg_medium'],
            fg=COLORS['text_primary'],
            anchor='w'
        )
        self.step_label.pack(fill=tk.X, pady=(0, 12))
        
        # Custom progress bar frame
        progress_frame = tk.Frame(progress_inner, bg=COLORS['bg_dark'], height=24)
        progress_frame.pack(fill=tk.X, pady=(0, 8))
        progress_frame.pack_propagate(False)
        
        self.progress_fill = tk.Frame(progress_frame, bg=COLORS['accent_blue'], width=0)
        self.progress_fill.place(x=0, y=0, relheight=1)
        self.progress_value = 0
        
        # Step counter
        self.counter_label = tk.Label(
            progress_inner,
            text="Ready to install",
            font=("Segoe UI", 9),
            bg=COLORS['bg_medium'],
            fg=COLORS['text_muted'],
            anchor='w'
        )
        self.counter_label.pack(fill=tk.X)
        
        # Log area with custom styling
        log_container = tk.Frame(progress_inner, bg=COLORS['bg_dark'], highlightbackground=COLORS['bg_light'], highlightthickness=1)
        log_container.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        
        self.log_text = tk.Text(
            log_container,
            height=8,
            font=("Consolas", 9),
            wrap=tk.WORD,
            state=tk.DISABLED,
            bg=COLORS['bg_dark'],
            fg=COLORS['text_secondary'],
            insertbackground=COLORS['text_primary'],
            selectbackground=COLORS['accent_blue'],
            relief=tk.FLAT,
            padx=10,
            pady=8,
            borderwidth=0
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Configure text tags for colored log messages
        self.log_text.tag_configure('success', foreground=COLORS['success'])
        self.log_text.tag_configure('warning', foreground=COLORS['warning'])
        self.log_text.tag_configure('error', foreground=COLORS['error'])
        self.log_text.tag_configure('info', foreground=COLORS['text_secondary'])
        
        scrollbar = tk.Scrollbar(log_container, command=self.log_text.yview, bg=COLORS['bg_medium'], troughcolor=COLORS['bg_dark'])
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # ===== Buttons =====
        button_frame = tk.Frame(main_frame, bg=COLORS['bg_dark'])
        button_frame.pack(fill=tk.X)
        
        # Custom styled buttons
        self.cancel_btn = tk.Button(
            button_frame,
            text="Cancel",
            command=self._cancel,
            font=("Segoe UI", 10),
            bg=COLORS['bg_light'],
            fg=COLORS['text_secondary'],
            activebackground=COLORS['bg_medium'],
            activeforeground=COLORS['text_primary'],
            relief=tk.FLAT,
            padx=25,
            pady=10,
            cursor="hand2"
        )
        self.cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        self.install_btn = tk.Button(
            button_frame,
            text="Install",
            command=self._start_installation,
            font=("Segoe UI", 10, "bold"),
            bg=COLORS['accent_blue'],
            fg=COLORS['text_primary'],
            activebackground=COLORS['accent'],
            activeforeground=COLORS['text_primary'],
            relief=tk.FLAT,
            padx=30,
            pady=10,
            cursor="hand2"
        )
        self.install_btn.pack(side=tk.RIGHT)
        
        # Button hover effects
        self._bind_hover(self.install_btn, COLORS['accent_blue'], '#7b8eea')
        self._bind_hover(self.cancel_btn, COLORS['bg_light'], COLORS['bg_medium'])
    
    def _bind_hover(self, btn, normal_color, hover_color):
        """Bind hover effect to button."""
        btn.bind('<Enter>', lambda e: btn.configure(bg=hover_color))
        btn.bind('<Leave>', lambda e: btn.configure(bg=normal_color))
    
    def _update_progress_bar(self, percent):
        """Update custom progress bar."""
        self.progress_value = percent
        # Calculate width based on percentage
        total_width = 450  # Approximate width
        fill_width = int((percent / 100) * total_width)
        self.progress_fill.configure(width=fill_width)
        self.root.update_idletasks()
    
    def _log(self, message: str, level: str = "info"):
        """Add message to log area with color."""
        self.log_text.config(state=tk.NORMAL)
        
        # Add prefix based on level
        prefix_map = {
            "info": ("  ", "info"),
            "success": ("✓ ", "success"),
            "warning": ("⚠ ", "warning"),
            "error": ("✗ ", "error")
        }
        prefix, tag = prefix_map.get(level, ("  ", "info"))
        
        self.log_text.insert(tk.END, f"{prefix}{message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()
    
    def _update_progress(self, step: InstallStep, status: str):
        """Update progress display."""
        self.current_step = step.number
        percent = int((step.number / self.total_steps) * 100)
        
        self.step_label.config(text=step.name)
        self._update_progress_bar(percent)
        self.counter_label.config(text=f"Step {step.number} of {self.total_steps} • {step.time_estimate}")
        
        self._log(status)
    
    def _start_installation(self):
        """Start the installation in a background thread."""
        self.install_btn.config(state=tk.DISABLED, bg=COLORS['text_muted'])
        self._log("Starting installation...", "info")
        
        # Run in thread to keep UI responsive
        thread = threading.Thread(target=self._run_installation, daemon=True)
        thread.start()
    
    def _run_installation(self):
        """Run the actual installation (called in background thread)."""
        try:
            success = self.installer.run(
                progress_callback=self._update_progress,
                log_callback=self._log
            )
            
            if success:
                self.root.after(0, self._installation_complete)
            else:
                self.root.after(0, self._installation_failed)
                
        except Exception as e:
            self.root.after(0, lambda: self._installation_error(str(e)))
    
    def _installation_complete(self):
        """Handle successful installation."""
        self._update_progress_bar(100)
        self.step_label.config(text="✨ Installation Complete!", fg=COLORS['success'])
        self._log("Installation completed successfully!", "success")
        self._log("Ready to launch PGVectorRAGIndexer!", "info")
        
        self.install_btn.config(
            text="🚀 Launch App",
            state=tk.NORMAL,
            bg=COLORS['accent_green'],
            command=self._launch_app
        )
        self._bind_hover(self.install_btn, COLORS['accent_green'], '#00e6b8')
        self.cancel_btn.config(text="Close")
    
    def _installation_failed(self):
        """Handle failed installation."""
        self.step_label.config(text="Installation Failed", fg=COLORS['error'])
        self._log("Installation failed. Check the log above for details.", "error")
        self.install_btn.config(
            text="Retry",
            state=tk.NORMAL,
            bg=COLORS['accent'],
            command=self._start_installation
        )
    
    def _installation_error(self, error: str):
        """Handle installation error."""
        self._log(f"Error: {error}", "error")
        messagebox.showerror("Installation Error", f"An error occurred:\n\n{error}")
        self._installation_failed()
    
    def _launch_app(self):
        """Launch the installed application."""
        try:
            self.installer.launch_app()
            self.root.destroy()
        except Exception as e:
            messagebox.showerror("Launch Error", f"Could not launch app:\n\n{e}")
    
    def _cancel(self):
        """Cancel installation and close."""
        if self.installer.is_running:
            if messagebox.askyesno("Cancel Installation", 
                                   "Installation is in progress. Are you sure you want to cancel?"):
                self.installer.cancel()
                self.root.destroy()
        else:
            self.root.destroy()
    
    def run(self):
        """Start the GUI event loop."""
        self.root.mainloop()


def main():
    """Entry point."""
    app = InstallerGUI()
    app.run()


if __name__ == "__main__":
    main()
