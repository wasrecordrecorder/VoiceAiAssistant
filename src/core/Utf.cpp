#include "core/Utf.hpp"

#include <Windows.h>

#include <stdexcept>

namespace webviewda::core
{
std::string ToUtf8(std::wstring_view value)
{
    if (value.empty())
    {
        return {};
    }

    const int size = WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    if (size <= 0)
    {
        throw std::runtime_error("WideCharToMultiByte failed.");
    }

    std::string result(static_cast<std::size_t>(size), '\0');
    if (WideCharToMultiByte(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size, nullptr, nullptr) <= 0)
    {
        throw std::runtime_error("WideCharToMultiByte failed.");
    }

    return result;
}

std::wstring FromUtf8(std::string_view value)
{
    if (value.empty())
    {
        return {};
    }

    const int size = MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), nullptr, 0);
    if (size <= 0)
    {
        throw std::runtime_error("MultiByteToWideChar failed.");
    }

    std::wstring result(static_cast<std::size_t>(size), L'\0');
    if (MultiByteToWideChar(CP_UTF8, 0, value.data(), static_cast<int>(value.size()), result.data(), size) <= 0)
    {
        throw std::runtime_error("MultiByteToWideChar failed.");
    }

    return result;
}
}
