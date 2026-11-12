======================================================================
          SHADOW SYSTEM HUD v2.1 - WINDOWS 11 INSTALLER GUIDE
======================================================================

OPTION 1: 1-CLICK AUTOMATIC INSTALLER (RECOMMENDED)
----------------------------------------------------------------------
1. Right-click Shadow_System_HUD_Installer_v2.zip and click "Extract All...".
2. Double-click:  Install_Shadow_System_HUD.bat
   - Installs directly inside the terminal with live progress [1/5]..[5/5]
   - Installs to: %LOCALAPPDATA%\Programs\ShadowSystemHUD
   - Creates a Desktop shortcut ("Shadow System HUD") with a custom icon
   - Creates a Start Menu shortcut & registers in Windows Installed Apps
   - Configures Windows Startup auto-launch (no console window flash)
   - Auto-detects MinGW64 / GCC and Lively Wallpaper
   - Automatically launches the Shadow System HUD on your screen!

OPTION 2: BUILD A STANDALONE NATIVE .EXE FILE
----------------------------------------------------------------------
- Double-click:  Build_Standalone_EXE.bat
- Compiles %LOCALAPPDATA%\Programs\ShadowSystemHUD\ShadowSystemHUD.exe
  and links your Desktop & Start Menu shortcuts directly to it.

UNINSTALLING
----------------------------------------------------------------------
- Double-click Uninstall_Shadow_System_HUD.bat (or uninstall directly
  from Windows 11 Settings -> Apps -> Installed Apps -> Shadow System HUD).
======================================================================

WHAT'S NEW IN 2.1
----------------------------------------------------------------------
- Remove wallpaper (main window): the HUD stops managing the wallpaper, puts back your
  original Windows wallpaper (or a plain colour if it was never recorded) and keeps the
  widgets floating over your desktop. Pick "Set wallpaper" any time to go back.
- Custom widgets (main window > Add custom widget, or Widgets... > CUSTOM WIDGETS):
    * PNG / GIF / WebP / JPG / BMP, or a .zip containing one; from a file or a direct link.
    * Animated GIF / WebP / APNG play live. Size + opacity sliders, drag in "Edit layout"
      (mouse wheel resizes). Up to 12. Files are copied to %USERPROFILE%\.shadow_system_hud\custom_widgets
    * Needs the live overlay (Overlay mode auto/live). In baked mode the first frame is
      stamped into the wallpaper instead.
    * Not supported: HTML / Rainmeter / .exe widgets, SVG.
- Faster: no more 'tasklist' process every 15 s, workspace scan moved off the UI thread
  and cached, baked wallpaper re-render ~8x faster, UI redraws only what changed.
- The bottom log is now a status strip (click it for the full history).
======================================================================
