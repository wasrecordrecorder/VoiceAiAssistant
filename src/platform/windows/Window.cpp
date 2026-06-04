#include "platform/windows/Window.hpp"

#include "core/BuildInfo.hpp"
#include "core/Utf.hpp"
#include "webview/WebViewHost.hpp"
#include "platform/windows/AppMessages.hpp"
#include "platform/windows/OverlayWindow.hpp"

#include <nlohmann/json.hpp>

#include <dwmapi.h>
#include <windowsx.h>

#include <exception>
#include <stdexcept>

namespace
{
constexpr wchar_t WindowClassName[] = L"WebViewDA.Voice.Window";
constexpr int WindowWidth = 1320;
constexpr int WindowHeight = 840;
constexpr int BorderSize = 7;
}

namespace webviewda::platform::windows
{
Window::Window(HINSTANCE instance) : instance_(instance)
{
}

Window::~Window()
{
    UnregisterHotKey(window_, 1);
    pushToTalk_.Remove();
    overlay_.reset();
    webView_.reset();
    backend_.Stop();
    tray_.Remove();

    if (window_ != nullptr && IsWindow(window_))
    {
        DestroyWindow(window_);
    }
}

void Window::Register()
{
    WNDCLASSEXW descriptor{};
    descriptor.cbSize = sizeof(descriptor);
    descriptor.style = CS_HREDRAW | CS_VREDRAW;
    descriptor.lpfnWndProc = &Window::StaticWindowProc;
    descriptor.hInstance = instance_;
    descriptor.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    descriptor.hbrBackground = reinterpret_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
    descriptor.lpszClassName = WindowClassName;

    if (RegisterClassExW(&descriptor) == 0 && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
    {
        throw std::runtime_error("RegisterClassExW failed.");
    }
}

void Window::Create()
{
    Register();

    const int x = (GetSystemMetrics(SM_CXSCREEN) - WindowWidth) / 2;
    const int y = (GetSystemMetrics(SM_CYSCREEN) - WindowHeight) / 2;

    window_ = CreateWindowExW(
        WS_EX_APPWINDOW,
        WindowClassName,
        core::ProductNameWide.data(),
        WS_POPUP | WS_THICKFRAME | WS_MINIMIZEBOX | WS_MAXIMIZEBOX,
        x,
        y,
        WindowWidth,
        WindowHeight,
        nullptr,
        nullptr,
        instance_,
        this);

    if (window_ == nullptr)
    {
        throw std::runtime_error("CreateWindowExW failed.");
    }

    ApplyVisuals();
    tray_.Initialize(window_);
    RegisterHotKey(window_, 1, MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, VK_SPACE);
    pushToTalk_.Install(window_);
}

void Window::ApplyVisuals()
{
    const BOOL dark = TRUE;
    const DWM_WINDOW_CORNER_PREFERENCE corner = DWMWCP_ROUND;
    DwmSetWindowAttribute(window_, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof(dark));
    DwmSetWindowAttribute(window_, DWMWA_WINDOW_CORNER_PREFERENCE, &corner, sizeof(corner));
}

void Window::Show(int showCommand)
{
    ShowWindow(window_, showCommand);
    UpdateWindow(window_);
}

void Window::Restore()
{
    if (overlay_)
    {
        overlay_->Hide();
    }
    ShowWindow(window_, SW_SHOW);
    SetForegroundWindow(window_);
    SetFocus(window_);
}

void Window::HideToTray()
{
    ShowWindow(window_, SW_HIDE);
    if (overlay_ && widgetEnabled_)
    {
        overlay_->Show();
    }
}

LRESULT Window::HitTest(POINT cursor) const
{
    RECT bounds{};
    GetWindowRect(window_, &bounds);
    const bool left = cursor.x < bounds.left + BorderSize;
    const bool right = cursor.x >= bounds.right - BorderSize;
    const bool top = cursor.y < bounds.top + BorderSize;
    const bool bottom = cursor.y >= bounds.bottom - BorderSize;

    if (top && left)
    {
        return HTTOPLEFT;
    }
    if (top && right)
    {
        return HTTOPRIGHT;
    }
    if (bottom && left)
    {
        return HTBOTTOMLEFT;
    }
    if (bottom && right)
    {
        return HTBOTTOMRIGHT;
    }
    if (left)
    {
        return HTLEFT;
    }
    if (right)
    {
        return HTRIGHT;
    }
    if (top)
    {
        return HTTOP;
    }
    if (bottom)
    {
        return HTBOTTOM;
    }
    return HTCLIENT;
}

LRESULT CALLBACK Window::StaticWindowProc(HWND window, UINT message, WPARAM wParam, LPARAM lParam)
{
    Window* instance = reinterpret_cast<Window*>(GetWindowLongPtrW(window, GWLP_USERDATA));

    if (message == WM_NCCREATE)
    {
        const auto* create = reinterpret_cast<CREATESTRUCTW*>(lParam);
        instance = static_cast<Window*>(create->lpCreateParams);
        instance->window_ = window;
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(instance));
    }

    if (instance == nullptr)
    {
        return DefWindowProcW(window, message, wParam, lParam);
    }

    return instance->WindowProc(message, wParam, lParam);
}

LRESULT Window::WindowProc(UINT message, WPARAM wParam, LPARAM lParam)
{
    switch (message)
    {
    case WM_CREATE:
        try
        {
            backend_.Start();
            webView_ = std::make_shared<webview::WebViewHost>(window_, backend_.Connection());
            webView_->Initialize();
            overlay_ = std::make_unique<OverlayWindow>(instance_, window_);
            overlay_->Create();
            overlay_->Configure(widgetVertical_);
        }
        catch (const std::exception& error)
        {
            const auto text = core::FromUtf8(error.what());
            MessageBoxW(window_, text.c_str(), core::ProductNameWide.data(), MB_OK | MB_ICONERROR);
            return -1;
        }
        return 0;

    case WM_NCCALCSIZE:
        if (wParam == TRUE)
        {
            return 0;
        }
        break;

    case WM_NCHITTEST:
    {
        const POINT cursor{GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam)};
        const LRESULT test = HitTest(cursor);
        if (test != HTCLIENT)
        {
            return test;
        }
        break;
    }

    case WM_SIZE:
        if (webView_)
        {
            webView_->Resize();
        }
        return 0;

    case WM_GETMINMAXINFO:
    {
        auto* info = reinterpret_cast<MINMAXINFO*>(lParam);
        info->ptMinTrackSize.x = 940;
        info->ptMinTrackSize.y = 610;
        return 0;
    }

    case RestoreMainMessage:
        Restore();
        return 0;

    case ConfigurePushToTalkMessage:
        pushToTalk_.Configure(static_cast<UINT>(wParam), static_cast<UINT>(lParam) >> 8, (static_cast<UINT>(lParam) & 1U) != 0);
        return 0;

    case ConfigureWidgetMessage:
        widgetEnabled_ = wParam != 0;
        widgetVertical_ = lParam != 0;
        if (overlay_)
        {
            overlay_->Configure(widgetVertical_);
            if (!widgetEnabled_)
            {
                overlay_->Hide();
            }
        }
        return 0;

    case WM_COPYDATA:
    {
        const auto* data = reinterpret_cast<const COPYDATASTRUCT*>(lParam);
        if (data != nullptr && data->dwData == WidgetStatusCopyData && overlay_ && data->lpData != nullptr)
        {
            try
            {
                const std::string payload(reinterpret_cast<const char*>(data->lpData), data->cbData);
                const auto value = nlohmann::json::parse(payload);
                overlay_->Update(core::FromUtf8(value.value("state", "Готов")), core::FromUtf8(value.value("step", "Ожидаю команду")));
                return TRUE;
            }
            catch (...)
            {
                return FALSE;
            }
        }
        break;
    }

    case PushToTalkDownMessage:
        if (webView_)
        {
            webView_->PostEvent("ptt.down", nlohmann::json::object());
        }
        return 0;

    case PushToTalkUpMessage:
        if (webView_)
        {
            webView_->PostEvent("ptt.up", nlohmann::json::object());
        }
        return 0;

    case WM_HOTKEY:
        if (wParam == 1)
        {
            Restore();
        }
        return 0;

    case TrayIcon::CallbackMessage:
        if (LOWORD(lParam) == WM_LBUTTONUP || LOWORD(lParam) == NIN_SELECT)
        {
            Restore();
        }
        else if (LOWORD(lParam) == WM_RBUTTONUP || LOWORD(lParam) == WM_CONTEXTMENU)
        {
            const UINT command = tray_.ShowMenu(window_);
            if (command == TrayIcon::ShowCommand)
            {
                Restore();
            }
            else if (command == TrayIcon::ExitCommand)
            {
                exiting_ = true;
                DestroyWindow(window_);
            }
        }
        return 0;

    case WM_COMMAND:
        if (LOWORD(wParam) == TrayIcon::ExitCommand)
        {
            exiting_ = true;
            DestroyWindow(window_);
            return 0;
        }
        return 0;

    case WM_CLOSE:
        if (!exiting_)
        {
            HideToTray();
            return 0;
        }
        DestroyWindow(window_);
        return 0;

    case WM_DESTROY:
        pushToTalk_.Remove();
        overlay_.reset();
        webView_.reset();
        backend_.Stop();
        tray_.Remove();
        PostQuitMessage(0);
        return 0;

    default:
        break;
    }

    return DefWindowProcW(window_, message, wParam, lParam);
}
}
