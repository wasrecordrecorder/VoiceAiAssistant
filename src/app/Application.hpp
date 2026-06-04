#pragma once

#include "platform/windows/ComApartment.hpp"

#include <Windows.h>

namespace webviewda::app
{
class Application final
{
public:
    explicit Application(HINSTANCE instance);
    ~Application();
    int Run(int showCommand);

private:
    HINSTANCE instance_;
    HANDLE mutex_{};
    bool alreadyRunning_{};
    platform::windows::ComApartment apartment_;
};
}
