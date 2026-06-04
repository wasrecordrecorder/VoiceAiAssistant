#pragma once

#include <string>
#include <string_view>

namespace webviewda::core
{
std::string ToUtf8(std::wstring_view value);
std::wstring FromUtf8(std::string_view value);
}
