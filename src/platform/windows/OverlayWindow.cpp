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
constexpr int HorizontalWidth = 154;
constexpr int HorizontalHeight = 44;
constexpr int VerticalWidth = 54;
constexpr int VerticalHeight = 64;
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
    if (value.rfind(L"Р С›РЎвЂљР Р†Р ВµРЎвЂљ:", 0) == 0)
    {
        return L"Р С›РЎвЂљР Р†Р ВµРЎвЂљ Р С–Р С•РЎвЂљР С•Р Р†";
    }
    if (value.rfind(L"Р вЂ”Р В°Р С—РЎР‚Р С•РЎРѓ:", 0) == 0)
    {
        return L"Р вЂ”Р В°Р С—РЎР‚Р С•РЎРѓ Р С—РЎР‚Р С‘Р Р…РЎРЏРЎвЂљ";
    }
    if (value.rfind(L"Р ВР Р…РЎРѓРЎвЂљРЎР‚РЎС“Р СР ВµР Р…РЎвЂљ:", 0) == 0)
    {
        value.replace(0, 11, L"Tool:");
    }
    if (value.size() <= limit)
    {
        return value;
    }
    return value.substr(0, limit - 1) + L"РІР‚В¦";
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
    state_ = state.empty() ? L"Р вЂњР С•РЎвЂљР С•Р Р†" : CompactText(std::move(state), vertical_ ? 8 : 14);
    step_ = step.empty() ? L"Р С›Р В¶Р С‘Р Т‘Р В°РЎР‹" : CompactText(std::move(step), vertical_ ? 8 : 24);
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
    if (vertical_)
    {
        const int left = (VerticalWidth - 24) / 2;
        return point.x >= left && point.x < left + 24 && point.y >= VerticalHeight - 29 && point.y < VerticalHeight - 5;
    }
    return point.x >= HorizontalWidth - 36 && point.x < HorizontalWidth - 10 && point.y >= 12 && point.y < 38;
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

    const HBRUSH background = CreateSolidBrush(RGB(6, 8, 11));
    FillRect(target, &bounds, background);
    DeleteObject(background);

    const HBRUSH card = CreateSolidBrush(RGB(9, 12, 16));
    const HPEN cardBorder = CreatePen(PS_SOLID, 1, RGB(32, 38, 47));
    const auto oldCardBrush = SelectObject(target, card);
    const auto oldCardPen = SelectObject(target, cardBorder);
    RoundRect(target, 0, 0, width, height, vertical_ ? 16 : 18, vertical_ ? 16 : 18);
    SelectObject(target, oldCardPen);
    SelectObject(target, oldCardBrush);
    DeleteObject(cardBorder);
    DeleteObject(card);

    const bool error = state_ == L"Р С›РЎв‚¬Р С‘Р В±Р С”Р В°";
    const HBRUSH indicator = CreateSolidBrush(error ? RGB(218, 111, 111) : RGB(231, 236, 245));
    const auto oldIndicatorBrush = SelectObject(target, indicator);
    const auto oldIndicatorPen = SelectObject(target, GetStockObject(NULL_PEN));
    if (vertical_)
    {
        Ellipse(target, width / 2 - 4, 9, width / 2 + 4, 17);
    }
    else
    {
        RoundRect(target, 12, 15, 16, height - 15, 4, 4);
    }
    SelectObject(target, oldIndicatorPen);
    SelectObject(target, oldIndicatorBrush);
    DeleteObject(indicator);

    SetBkMode(target, TRANSPARENT);
    const HFONT title = CreateFontW(vertical_ ? -11 : -13, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI Variable");
    const HFONT body = CreateFontW(-10, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE, DEFAULT_CHARSET, OUT_DEFAULT_PRECIS,
        CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI Variable");

    const auto previous = SelectObject(target, title);
    SetTextColor(target, RGB(237, 241, 247));
    RECT titleBounds = vertical_ ? RECT{5, 21, width - 5, 37} : RECT{24, 8, width - 44, 25};
    DrawTextW(target, state_.c_str(), -1, &titleBounds, vertical_ ? DT_CENTER | DT_SINGLELINE | DT_END_ELLIPSIS : DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS | DT_VCENTER);
    SelectObject(target, body);
    SetTextColor(target, RGB(124, 135, 150));
    RECT stepBounds = vertical_ ? RECT{5, 35, width - 5, 47} : RECT{24, 25, width - 44, 41};
    DrawTextW(target, step_.c_str(), -1, &stepBounds, vertical_ ? DT_CENTER | DT_SINGLELINE | DT_END_ELLIPSIS : DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS | DT_VCENTER);
    SelectObject(target, previous);
    DeleteObject(title);
    DeleteObject(body);

    const int buttonSize = vertical_ ? 24 : 26;
    const int buttonLeft = vertical_ ? (width - buttonSize) / 2 : width - 36;
    const int buttonTop = vertical_ ? height - 29 : 12;
    const HBRUSH button = CreateSolidBrush(RGB(15, 19, 25));
    const HPEN border = CreatePen(PS_SOLID, 1, RGB(42, 49, 60));
    const auto oldBrush = SelectObject(target, button);
    const auto oldPen = SelectObject(target, border);
    RoundRect(target, buttonLeft, buttonTop, buttonLeft + buttonSize, buttonTop + buttonSize, 9, 9);
    SelectObject(target, oldPen);
    SelectObject(target, oldBrush);
    DeleteObject(border);
    DeleteObject(button);

    const HPEN arrow = CreatePen(PS_SOLID, 2, RGB(185, 196, 211));
    const auto oldArrow = SelectObject(target, arrow);
    MoveToEx(target, buttonLeft + 7, buttonTop + buttonSize - 8, nullptr);
    LineTo(target, buttonLeft + buttonSize - 7, buttonTop + 7);
    MoveToEx(target, buttonLeft + 10, buttonTop + 7, nullptr);
    LineTo(target, buttonLeft + buttonSize - 7, buttonTop + 7);
    LineTo(target, buttonLeft + buttonSize - 7, buttonTop + 10);
    SelectObject(target, oldArrow);
    DeleteObject(arrow);
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
