#pragma once

#include "backend/BackendProcess.hpp"
#include "platform/windows/TrayIcon.hpp"
#include "platform/windows/PushToTalk.hpp"

#include <Windows.h>

#include <memory>

namespace webviewda::platform::windows
{
class OverlayWindow;
}

namespace webviewda::webview
{
class WebViewHost;
}

namespace webviewda::platform::windows
{
class Window final
{
public:
    explicit Window(HINSTANCE instance);
    ~Window();

    Window(const Window&) = delete;
    Window& operator=(const Window&) = delete;

    void Create();
    void Show(int showCommand);

private:
    static LRESULT CALLBACK StaticWindowProc(HWND window, UINT message, WPARAM wParam, LPARAM lParam);
    LRESULT WindowProc(UINT message, WPARAM wParam, LPARAM lParam);
    void Register();
    void ApplyVisuals();
    void Restore();
    void HideToTray();
    LRESULT HitTest(POINT cursor) const;

    HINSTANCE instance_;
    HWND window_{};
    bool exiting_{};
    backend::BackendProcess backend_;
    TrayIcon tray_;
    PushToTalk pushToTalk_;
    bool widgetEnabled_{true};
    bool widgetVertical_{};
    std::unique_ptr<OverlayWindow> overlay_;
    std::shared_ptr<webview::WebViewHost> webView_;
};
}
