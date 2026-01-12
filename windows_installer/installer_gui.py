"""
PGVectorRAGIndexer Windows Installer - GUI
A simple Tkinter-based installer with progress display.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys
import os

# Add parent directory for imports when running from source
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from installer_logic import Installer, InstallStep


class InstallerGUI:
    """Main installer GUI window."""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("PGVectorRAGIndexer Setup")
        self.root.geometry("550x450")
        self.root.resizable(False, False)
        
        # Center window on screen
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - 550) // 2
        y = (self.root.winfo_screenheight() - 450) // 2
        self.root.geometry(f"550x450+{x}+{y}")
        
        # Set icon if available
        try:
            self.root.iconbitmap("icon.ico")
        except:
            pass
        
        self.installer = Installer()
        self.current_step = 0
        self.total_steps = len(self.installer.steps)
        
        self._create_widgets()
        self._apply_styles()
    
    def _create_widgets(self):
        """Create all GUI widgets."""
        # Main container
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Header
        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 20))
        
        title = ttk.Label(
            header_frame, 
            text="🔍 PGVectorRAGIndexer",
            font=("Segoe UI", 18, "bold")
        )
        title.pack()
        
        subtitle = ttk.Label(
            header_frame,
            text="One-Click Installer",
            font=("Segoe UI", 11),
            foreground="gray"
        )
        subtitle.pack()
        
        # Status area
        status_frame = ttk.LabelFrame(main_frame, text="Installation Progress", padding="15")
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 15))
        
        # Current step label
        self.step_label = ttk.Label(
            status_frame,
            text="Click 'Install' to begin",
            font=("Segoe UI", 10, "bold")
        )
        self.step_label.pack(anchor=tk.W, pady=(0, 10))
        
        # Progress bar
        self.progress = ttk.Progressbar(
            status_frame,
            length=480,
            mode='determinate',
            maximum=100
        )
        self.progress.pack(fill=tk.X, pady=(0, 10))
        
        # Step counter
        self.counter_label = ttk.Label(
            status_frame,
            text="Step 0 of 0",
            font=("Segoe UI", 9),
            foreground="gray"
        )
        self.counter_label.pack(anchor=tk.W)
        
        # Log area (scrollable)
        log_frame = ttk.Frame(status_frame)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        self.log_text = tk.Text(
            log_frame,
            height=8,
            font=("Consolas", 9),
            wrap=tk.WORD,
            state=tk.DISABLED,
            background="#1e1e1e",
            foreground="#d4d4d4"
        )
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # Buttons
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        self.install_btn = ttk.Button(
            button_frame,
            text="Install",
            command=self._start_installation,
            width=15
        )
        self.install_btn.pack(side=tk.RIGHT, padx=(10, 0))
        
        self.cancel_btn = ttk.Button(
            button_frame,
            text="Cancel",
            command=self._cancel,
            width=15
        )
        self.cancel_btn.pack(side=tk.RIGHT)
    
    def _apply_styles(self):
        """Apply custom styles."""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Custom button style
        style.configure(
            "TButton",
            padding=8,
            font=("Segoe UI", 10)
        )
        
        # Progress bar color
        style.configure(
            "TProgressbar",
            troughcolor="#e0e0e0",
            background="#4CAF50",
            thickness=20
        )
    
    def _log(self, message: str, level: str = "info"):
        """Add message to log area."""
        self.log_text.config(state=tk.NORMAL)
        
        # Add prefix based on level
        prefix = {
            "info": "  ",
            "success": "✓ ",
            "warning": "! ",
            "error": "✗ "
        }.get(level, "  ")
        
        self.log_text.insert(tk.END, f"{prefix}{message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.root.update_idletasks()
    
    def _update_progress(self, step: InstallStep, status: str):
        """Update progress display."""
        self.current_step = step.number
        percent = int((step.number / self.total_steps) * 100)
        
        self.step_label.config(text=f"{step.name}")
        self.progress['value'] = percent
        self.counter_label.config(text=f"Step {step.number} of {self.total_steps} • {step.time_estimate}")
        
        self._log(status)
        self.root.update_idletasks()
    
    def _start_installation(self):
        """Start the installation in a background thread."""
        self.install_btn.config(state=tk.DISABLED)
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
        self.progress['value'] = 100
        self.step_label.config(text="Installation Complete!")
        self._log("Installation completed successfully!", "success")
        self._log("Starting PGVectorRAGIndexer...", "info")
        
        self.install_btn.config(text="Launch App", state=tk.NORMAL)
        self.install_btn.config(command=self._launch_app)
        self.cancel_btn.config(text="Close")
    
    def _installation_failed(self):
        """Handle failed installation."""
        self.step_label.config(text="Installation Failed")
        self._log("Installation failed. Check the log above for details.", "error")
        self.install_btn.config(text="Retry", state=tk.NORMAL)
        self.install_btn.config(command=self._start_installation)
    
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
