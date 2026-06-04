#pragma once

#include <Windows.h>

#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string_view>

namespace webviewda::core
{
inline void Ensure(HRESULT result, std::string_view operation)
{
    if (SUCCEEDED(result))
    {
        return;
    }

    std::ostringstream message;
    message << operation << " failed with HRESULT 0x" << std::uppercase << std::hex
            << static_cast<unsigned long>(result);
    throw std::runtime_error(message.str());
}
}
