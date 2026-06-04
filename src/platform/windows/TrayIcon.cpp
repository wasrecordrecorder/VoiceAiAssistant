#include "platform/windows/TrayIcon.hpp"

#include "core/BuildInfo.hpp"

namespace webviewda::platform::windows
{
TrayIcon::~TrayIcon()
{
    Remove();
}

void TrayIcon::Initialize(HWND window)
{
    data_.cbSize = sizeof(data_);
    data_.hWnd = window;
    data_.uID = 1;
    data_.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP;
    data_.uCallbackMessage = CallbackMessage;
    data_.hIcon = LoadIconW(nullptr, IDI_APPLICATION);
    wcscpy_s(data_.szTip, core::ProductNameWide.data());

    if (Shell_NotifyIconW(NIM_ADD, &data_))
    {
        data_.uVersion = NOTIFYICON_VERSION_4;
        Shell_NotifyIconW(NIM_SETVERSION, &data_);
        active_ = true;
    }
}

void TrayIcon::Remove()
{
    if (active_)
    {
        Shell_NotifyIconW(NIM_DELETE, &data_);
        active_ = false;
    }
}

UINT TrayIcon::ShowMenu(HWND window) const
{
    const HMENU menu = CreatePopupMenu();
    AppendMenuW(menu, MF_STRING, ShowCommand, L"Открыть WebViewDA");
    AppendMenuW(menu, MF_SEPARATOR, 0, nullptr);
    AppendMenuW(menu, MF_STRING, ExitCommand, L"Выйти");

    POINT cursor{};
    GetCursorPos(&cursor);
    SetForegroundWindow(window);
    const UINT command = TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, cursor.x, cursor.y, 0, window, nullptr);
    DestroyMenu(menu);
    PostMessageW(window, WM_NULL, 0, 0);
    return command;
}
}
