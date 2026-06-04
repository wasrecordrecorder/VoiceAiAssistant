#include "platform/windows/PushToTalk.hpp"

#include "platform/windows/AppMessages.hpp"

#include <stdexcept>

namespace
{
constexpr UINT CtrlModifier = 1;
constexpr UINT AltModifier = 2;
constexpr UINT ShiftModifier = 4;
constexpr UINT WinModifier = 8;

bool Down(int virtualKey)
{
    return (GetAsyncKeyState(virtualKey) & 0x8000) != 0;
}
}

namespace webviewda::platform::windows
{
PushToTalk::~PushToTalk()
{
    Remove();
}

void PushToTalk::Install(HWND target)
{
    target_ = target;
    active_ = this;
    hook_ = SetWindowsHookExW(WH_KEYBOARD_LL, &PushToTalk::HookProc, GetModuleHandleW(nullptr), 0);
    if (hook_ == nullptr)
    {
        active_ = nullptr;
        throw std::runtime_error("Push-to-talk keyboard hook could not be installed.");
    }
}

void PushToTalk::Configure(UINT virtualKey, UINT modifiers, bool enabled)
{
    key_ = virtualKey == 0 ? VK_F8 : virtualKey;
    modifiers_ = modifiers & 15U;
    enabled_ = enabled;
    pressed_ = false;
}

bool PushToTalk::ModifiersMatch() const
{
    const bool ctrl = Down(VK_CONTROL) || Down(VK_LCONTROL) || Down(VK_RCONTROL);
    const bool alt = Down(VK_MENU) || Down(VK_LMENU) || Down(VK_RMENU);
    const bool shift = Down(VK_SHIFT) || Down(VK_LSHIFT) || Down(VK_RSHIFT);
    const bool win = Down(VK_LWIN) || Down(VK_RWIN);
    return ctrl == ((modifiers_ & CtrlModifier) != 0) && alt == ((modifiers_ & AltModifier) != 0) &&
           shift == ((modifiers_ & ShiftModifier) != 0) && win == ((modifiers_ & WinModifier) != 0);
}

void PushToTalk::Remove()
{
    if (hook_ != nullptr)
    {
        UnhookWindowsHookEx(hook_);
        hook_ = nullptr;
    }
    if (active_ == this)
    {
        active_ = nullptr;
    }
}

LRESULT CALLBACK PushToTalk::HookProc(int code, WPARAM wParam, LPARAM lParam)
{
    if (code == HC_ACTION && active_ != nullptr && active_->enabled_)
    {
        const auto* input = reinterpret_cast<KBDLLHOOKSTRUCT*>(lParam);
        if (input->vkCode == active_->key_)
        {
            const bool down = wParam == WM_KEYDOWN || wParam == WM_SYSKEYDOWN;
            const bool up = wParam == WM_KEYUP || wParam == WM_SYSKEYUP;
            if (down && !active_->pressed_ && active_->ModifiersMatch())
            {
                active_->pressed_ = true;
                PostMessageW(active_->target_, PushToTalkDownMessage, 0, 0);
                return 1;
            }
            if (up && active_->pressed_)
            {
                active_->pressed_ = false;
                PostMessageW(active_->target_, PushToTalkUpMessage, 0, 0);
                return 1;
            }
        }
    }
    return CallNextHookEx(active_ == nullptr ? nullptr : active_->hook_, code, wParam, lParam);
}
}
