#pragma once

#include <Windows.h>

#include <string>

namespace webviewda::platform::windows
{
class OverlayWindow final
{
public:
    OverlayWindow(HINSTANCE instance, HWND owner);
    ~OverlayWindow();

    OverlayWindow(const OverlayWindow&) = delete;
    OverlayWindow& operator=(const OverlayWindow&) = delete;

    void Create();
    void Show();
    void Hide();
    void Update(std::wstring state, std::wstring step);
    void Configure(bool vertical);
    bool Visible() const noexcept;

private:
    static LRESULT CALLBACK StaticWindowProc(HWND window, UINT message, WPARAM wParam, LPARAM lParam);
    LRESULT WindowProc(UINT message, WPARAM wParam, LPARAM lParam);
    void Register();
    void ApplyVisuals();
    void PositionDefault();
    void RestoreMain();
    void Paint(HDC target);
    bool OverOpenButton(POINT point) const;

    HINSTANCE instance_;
    HWND owner_;
    HWND window_{};
    std::wstring state_{L"Готов"};
    std::wstring step_{L"Ожидаю команду"};
    bool customPosition_{};
    bool positioning_{};
    bool vertical_{};
};
}
