#include "platform/windows/OverlayWindow.hpp"

#include "core/BuildInfo.hpp"
#include "platform/windows/AppMessages.hpp"

#include <dwmapi.h>
#include <windowsx.h>

#include <stdexcept>
#include <utility>

namespace
{
constexpr wchar_t OverlayClassName[] = L"WebViewDA.Voice.Overlay";
constexpr int HorizontalWidth = 196;
constexpr int HorizontalHeight = 42;
constexpr int VerticalWidth = 168;
constexpr int VerticalHeight = 42;
constexpr int Margin = 16;

std::wstring CompactText(std::wstring value, std::size_t limit)
{
    for (auto& item : value)
    {
        if (item == L'\r' || item == L'\n' || item == L'\t')
        {
            item = L' ';
        }
    }
    while (!value.empty() && value.front() == L' ')
    {
        value.erase(value.begin());
    }
    while (!value.empty() && value.back() == L' ')
    {
        value.pop_back();
    }
    if (value.rfind(L"Ответ:", 0) == 0)
    {
        return L"Ответ готов";
    }
    if (value.rfind(L"Запрос:", 0) == 0)
    {
        return L"Запрос принят";
    }
    if (value.rfind(L"Инструмент:", 0) == 0)
    {
        value.replace(0, 11, L"Tool:");
    }
    if (value.size() <= limit)
    {
        return value;
    }
    return value.substr(0, limit - 1) + L"…";
}

int StatusKind(const std::wstring& state)
{
    if (state.find(L"Ошибка") != std::wstring::npos)
    {
        return 4;
    }
    if (state.find(L"Говор") != std::wstring::npos || state.find(L"Отвеч") != std::wstring::npos)
    {
        return 3;
    }
    if (state.find(L"Дума") != std::wstring::npos || state.find(L"Распозна") != std::wstring::npos)
    {
        return 2;
    }
    if (state.find(L"Слуш") != std::wstring::npos || state.find(L"Слышу") != std::wstring::npos || state.find(L"Рация") != std::wstring::npos || state.find(L"Диалог") != std::wstring::npos)
    {
        return 1;
    }
    return 0;
}

COLORREF DotColor(int status)
{
    switch (status)
    {
    case 1:
        return RGB(126, 200, 255);
    case 2:
        return RGB(214, 180, 255);
    case 3:
        return RGB(156, 240, 197);
    case 4:
        return RGB(255, 141, 141);
    default:
        return RGB(142, 153, 169);
    }
}

BYTE LightChannel(BYTE value)
{
    const int next = static_cast<int>(value) + 20;
    return static_cast<BYTE>(next > 255 ? 255 : next);
}
}

namespace webviewda::platform::windows
{
OverlayWindow::OverlayWindow(HINSTANCE instance, HWND owner) : instance_(instance), owner_(owner)
{
}

OverlayWindow::~OverlayWindow()
{
    if (window_ != nullptr && IsWindow(window_))
    {
        DestroyWindow(window_);
    }
}

void OverlayWindow::Register()
{
    WNDCLASSEXW descriptor{};
    descriptor.cbSize = sizeof(descriptor);
    descriptor.style = CS_HREDRAW | CS_VREDRAW | CS_DBLCLKS;
    descriptor.lpfnWndProc = &OverlayWindow::StaticWindowProc;
    descriptor.hInstance = instance_;
    descriptor.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    descriptor.hbrBackground = reinterpret_cast<HBRUSH>(GetStockObject(BLACK_BRUSH));
    descriptor.lpszClassName = OverlayClassName;
    if (RegisterClassExW(&descriptor) == 0 && GetLastError() != ERROR_CLASS_ALREADY_EXISTS)
    {
        throw std::runtime_error("Overlay window class could not be registered.");
    }
}

void OverlayWindow::Create()
{
    Register();
    window_ = CreateWindowExW(
        WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
        OverlayClassName,
        core::ProductNameWide.data(),
        WS_POPUP,
        0,
        0,
        HorizontalWidth,
        HorizontalHeight,
        nullptr,
        nullptr,
        instance_,
        this);
    if (window_ == nullptr)
    {
        throw std::runtime_error("Overlay window could not be created.");
    }
    ApplyVisuals();
    PositionDefault();
    customPosition_ = false;
}

void OverlayWindow::ApplyVisuals()
{
    const BOOL dark = TRUE;
    const DWM_WINDOW_CORNER_PREFERENCE corner = DWMWCP_ROUND;
    DwmSetWindowAttribute(window_, DWMWA_USE_IMMERSIVE_DARK_MODE, &dark, sizeof(dark));
    DwmSetWindowAttribute(window_, DWMWA_WINDOW_CORNER_PREFERENCE, &corner, sizeof(corner));
}

void OverlayWindow::PositionDefault()
{
    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    const int width = vertical_ ? VerticalWidth : HorizontalWidth;
    const int height = vertical_ ? VerticalHeight : HorizontalHeight;
    const int x = work.right - width - Margin;
    const int y = work.bottom - height - Margin;
    positioning_ = true;
    SetWindowPos(window_, HWND_TOPMOST, x, y, width, height, SWP_NOACTIVATE);
    positioning_ = false;
}

void OverlayWindow::Show()
{
    if (!customPosition_)
    {
        PositionDefault();
    }
    SetWindowPos(window_, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    ShowWindow(window_, SW_SHOWNOACTIVATE);
    InvalidateRect(window_, nullptr, FALSE);
}

void OverlayWindow::Hide()
{
    ShowWindow(window_, SW_HIDE);
}

void OverlayWindow::Update(std::wstring state, std::wstring step)
{
    state_ = state.empty() ? L"Готов" : CompactText(std::move(state), vertical_ ? 16 : 18);
    step_ = step.empty() ? L"Ожидаю команду" : CompactText(std::move(step), vertical_ ? 24 : 32);
    status_ = StatusKind(state_);
    if (window_ != nullptr)
    {
        InvalidateRect(window_, nullptr, FALSE);
    }
}

void OverlayWindow::Configure(bool vertical)
{
    vertical_ = vertical;
    customPosition_ = false;
    if (window_ != nullptr)
    {
        PositionDefault();
        InvalidateRect(window_, nullptr, FALSE);
    }
}

bool OverlayWindow::Visible() const noexcept
{
    return window_ != nullptr && IsWindowVisible(window_);
}

bool OverlayWindow::OverOpenButton(POINT point) const
{
    const int width = vertical_ ? VerticalWidth : HorizontalWidth;
    return point.x >= width - 34 && point.x < width - 8 && point.y >= 8 && point.y < 34;
}

void OverlayWindow::RestoreMain()
{
    Hide();
    PostMessageW(owner_, RestoreMainMessage, 0, 0);
}

void OverlayWindow::Paint(HDC target)
{
    RECT bounds{};
    GetClientRect(window_, &bounds);
    const int width = bounds.right - bounds.left;
    const int height = bounds.bottom - bounds.top;

    const HBRUSH background = CreateSolidBrush(RGB(8, 11, 16));
    FillRect(target, &bounds, background);
    DeleteObject(background);

    const HBRUSH card = CreateSolidBrush(status_ == 2 ? RGB(10, 10, 18) : RGB(8, 11, 16));
    const HPEN cardBorder = CreatePen(PS_SOLID, 1, status_ == 4 ? RGB(83, 43, 48) : RGB(35, 42, 53));
    const auto oldCardBrush = SelectObject(target, card);
    const auto oldCardPen = SelectObject(target, cardBorder);
    RoundRect(target, 0, 0, width, height, 18, 18);
    SelectObject(target, oldCardPen);
    SelectObject(target, oldCardBrush);
    DeleteObject(cardBorder);
    DeleteObject(card);

    const COLORREF dotColor = DotColor(status_);
    const HBRUSH dotGlow = CreateSolidBrush(RGB(LightChannel(GetRValue(dotColor)), LightChannel(GetGValue(dotColor)), LightChannel(GetBValue(dotColor))));
    const auto oldGlowBrush = SelectObject(target, dotGlow);
    const auto oldGlowPen = SelectObject(target, GetStockObject(NULL_PEN));
    Ellipse(target, 10, height / 2 - 7, 24, height / 2 + 7);
    SelectObject(target, oldGlowPen);
    SelectObject(target, oldGlowBrush);
    DeleteObject(dotGlow);

    const HBRUSH dot = CreateSolidBrush(dotColor);
    const auto oldDotBrush = SelectObject(target, dot);
    const auto oldDotPen = SelectObject(target, GetStockObject(NULL_PEN));
    Ellipse(target, 14, height / 2 - 4, 22, height / 2 + 4);
    SelectObject(target, oldDotPen);
    SelectObject(target, oldDotBrush);
    DeleteObject(dot);

    SetBkMode(target, TRANSPARENT);
    const HFONT title = CreateFontW(-12, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI Variable");
    const HFONT body = CreateFontW(-10, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI Variable");

    const auto previous = SelectObject(target, title);
    SetTextColor(target, RGB(244, 247, 251));
    RECT titleBounds{32, 7, width - 42, 23};
    DrawTextW(target, state_.c_str(), -1, &titleBounds, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS | DT_VCENTER);
    SelectObject(target, body);
    SetTextColor(target, RGB(139, 150, 166));
    RECT stepBounds{32, 21, width - 42, 36};
    DrawTextW(target, step_.c_str(), -1, &stepBounds, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS | DT_VCENTER);
    SelectObject(target, previous);
    DeleteObject(title);
    DeleteObject(body);

    const int buttonLeft = width - 34;
    const int buttonTop = 8;
    const HBRUSH button = CreateSolidBrush(RGB(15, 19, 25));
    const HPEN border = CreatePen(PS_SOLID, 1, RGB(43, 50, 62));
    const auto oldBrush = SelectObject(target, button);
    const auto oldPen = SelectObject(target, border);
    RoundRect(target, buttonLeft, buttonTop, buttonLeft + 26, buttonTop + 26, 10, 10);
    SelectObject(target, oldPen);
    SelectObject(target, oldBrush);
    DeleteObject(border);
    DeleteObject(button);

    const HBRUSH dots = CreateSolidBrush(RGB(174, 184, 199));
    const auto oldDotsBrush = SelectObject(target, dots);
    const auto oldDotsPen = SelectObject(target, GetStockObject(NULL_PEN));
    const int centerY = buttonTop + 13;
    for (int i = 0; i < 3; ++i)
    {
        const int centerX = buttonLeft + 9 + i * 4;
        Ellipse(target, centerX - 1, centerY - 1, centerX + 2, centerY + 2);
    }
    SelectObject(target, oldDotsPen);
    SelectObject(target, oldDotsBrush);
    DeleteObject(dots);
}

LRESULT CALLBACK OverlayWindow::StaticWindowProc(HWND window, UINT message, WPARAM wParam, LPARAM lParam)
{
    OverlayWindow* instance = reinterpret_cast<OverlayWindow*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (message == WM_NCCREATE)
    {
        const auto* create = reinterpret_cast<CREATESTRUCTW*>(lParam);
        instance = static_cast<OverlayWindow*>(create->lpCreateParams);
        instance->window_ = window;
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(instance));
    }
    return instance == nullptr ? DefWindowProcW(window, message, wParam, lParam) : instance->WindowProc(message, wParam, lParam);
}

LRESULT OverlayWindow::WindowProc(UINT message, WPARAM wParam, LPARAM lParam)
{
    switch (message)
    {
    case WM_NCHITTEST:
    {
        POINT point{GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam)};
        ScreenToClient(window_, &point);
        return OverOpenButton(point) ? HTCLIENT : HTCAPTION;
    }
    case WM_LBUTTONUP:
    {
        POINT point{GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam)};
        if (OverOpenButton(point))
        {
            RestoreMain();
        }
        return 0;
    }
    case WM_LBUTTONDBLCLK:
    case WM_NCLBUTTONDBLCLK:
        RestoreMain();
        return 0;
    case WM_MOVE:
        if (!positioning_)
        {
            customPosition_ = true;
        }
        return 0;
    case WM_PAINT:
    {
        PAINTSTRUCT paint{};
        const HDC target = BeginPaint(window_, &paint);
        Paint(target);
        EndPaint(window_, &paint);
        return 0;
    }
    case WM_ERASEBKGND:
        return 1;
    case WM_DESTROY:
        return 0;
    default:
        return DefWindowProcW(window_, message, wParam, lParam);
    }
}
}
