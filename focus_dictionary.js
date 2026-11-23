for (const window of workspace.windowList()) {
    if (window.caption === 'Ukijiten') {
        window.minimized = false;
        workspace.activeWindow = window;
        break;
    }
}
