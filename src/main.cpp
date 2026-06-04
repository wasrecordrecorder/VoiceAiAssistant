#include "app/Application.hpp"
#include "core/BuildInfo.hpp"
#include "core/Utf.hpp"

#include <Windows.h>

#include <cstdlib>
#include <exception>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE, PWSTR, int showCommand)
{
    try
    {
        webviewda::app::Application application(instance);
        return application.Run(showCommand);
    }
    catch (const std::exception& error)
    {
        const auto message = webviewda::core::FromUtf8(error.what());
        MessageBoxW(nullptr, message.c_str(), webviewda::core::ProductNameWide.data(), MB_OK | MB_ICONERROR);
        return EXIT_FAILURE;
    }
}
