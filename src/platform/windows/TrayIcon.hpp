#pragma once

#include <Windows.h>
#include <shellapi.h>

namespace webviewda::platform::windows
{
class TrayIcon final
{
public:
    static constexpr UINT CallbackMessage = WM_APP + 41;
    static constexpr UINT ShowCommand = 5001;
    static constexpr UINT ExitCommand = 5002;

    TrayIcon() = default;
    ~TrayIcon();

    TrayIcon(const TrayIcon&) = delete;
    TrayIcon& operator=(const TrayIcon&) = delete;

    void Initialize(HWND window);
    void Remove();
    UINT ShowMenu(HWND window) const;

private:
    NOTIFYICONDATAW data_{};
    bool active_{};
};
}
