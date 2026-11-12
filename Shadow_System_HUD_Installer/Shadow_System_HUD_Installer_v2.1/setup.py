from setuptools import setup

setup(
    name="shadow-system-hud",
    version="2.1.0",
    description="Shadow System HUD - Desktop Accountability & Audio-Synced Overlay Engine",
    py_modules=["shadow_system_hud"],
    install_requires=["Pillow>=9.0.0"],
    extras_require={"video": ["opencv-python>=4.5.0"]},
    entry_points={
        "console_scripts": [
            "shadow-hud-setup=shadow_system_hud:open_installer_gui",
        ],
        "gui_scripts": [
            "shadow-system-hud=shadow_system_hud:main",
        ],
    },
    python_requires=">=3.8",
)
