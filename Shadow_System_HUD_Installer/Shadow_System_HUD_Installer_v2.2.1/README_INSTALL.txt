======================================================================
          SHADOW SYSTEM HUD v2.2 - WINDOWS 11 INSTALLER GUIDE
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

WHAT'S NEW IN 2.2  -  NO BUILT-IN PLAN, FEED YOUR OWN
----------------------------------------------------------------------
- The built-in 23-day sprint is gone. First launch opens "Import plan" once; any time
  later use the main-window button "Import plan".
- Feed it ANYTHING: a file (.txt .md .html .docx .csv .tsv .json .pdf .zip), a link (web page,
  GitHub file, Google Doc / Sheet shared as "anyone with the link"), or paste the text.
  You see a preview of the days and tasks before anything changes.
- It understands: "Day 1: Title" headings, dated headings ("Sun 8 Nov - Loops", 2026-11-08),
  Week/Phase headings (shown as the phase name), plain headings, bullets / numbered / checkbox
  lists, tables with Day / Task columns, and plain lists (optionally N tasks per day).
- Any task that names a .c file (e.g. "armstrong.c - check Armstrong number") becomes an
  auto-verified code quest (compiles + runs). Want expected-output tests? Write the task as:
      code: prime.c | Prime? | 7 => YES ; 8 => NO
  Everything else is a tick-it-yourself quest. "Edit plan" opens the studio to fine-tune.
- Importing a new plan clears task progress (XP and streak stay). PDF import needs: pip install pypdf
- See example_plan.md for a ready-to-edit template.
======================================================================

UPDATE 2.2.1  -  HTML plans that showed no quests
----------------------------------------------------------------------
- Pages whose tasks live in <script> data (const PLAN = [...]) are now read, and so are pages
  that use plain <div>/<span> cards, <details> blocks or data-day="N" attributes.
- The preview now says "Today is Day N: K tasks due", or warns when today is outside the plan
  (wrong Day 1 date). The new "Today" button next to "Day 1 date" re-reads the plan starting today.
- If a page still imports wrongly: open it in the browser, press Ctrl+A, Ctrl+C and paste the text
  into the import box (works for any page).
======================================================================
