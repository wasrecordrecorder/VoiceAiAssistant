#pragma once

#include <Windows.h>

namespace webviewda::platform::windows
{
inline constexpr UINT RestoreMainMessage = WM_APP + 201;
inline constexpr UINT PushToTalkDownMessage = WM_APP + 202;
inline constexpr UINT PushToTalkUpMessage = WM_APP + 203;
inline constexpr UINT ConfigurePushToTalkMessage = WM_APP + 204;
inline constexpr UINT ConfigureWidgetMessage = WM_APP + 205;
inline constexpr UINT ConfigureWidgetOrientationMessage = WM_APP + 206;
inline constexpr ULONG_PTR WidgetStatusCopyData = 0x57445644;
}
