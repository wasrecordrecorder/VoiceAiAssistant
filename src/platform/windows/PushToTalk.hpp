#pragma once

#include <Windows.h>

namespace webviewda::platform::windows
{
class PushToTalk final
{
public:
    PushToTalk() = default;
    ~PushToTalk();

    PushToTalk(const PushToTalk&) = delete;
    PushToTalk& operator=(const PushToTalk&) = delete;

    void Install(HWND target);
    void Configure(UINT virtualKey, UINT modifiers, bool enabled);
    void Remove();

private:
    static LRESULT CALLBACK HookProc(int code, WPARAM wParam, LPARAM lParam);
    bool ModifiersMatch() const;

    inline static PushToTalk* active_{};
    HWND target_{};
    HHOOK hook_{};
    UINT key_{VK_F8};
    UINT modifiers_{};
    bool enabled_{};
    bool pressed_{};
};
}
