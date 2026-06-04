#include "app/Application.hpp"

#include "core/Result.hpp"
#include "platform/windows/Window.hpp"

#include <stdexcept>

namespace webviewda::app
{
Application::Application(HINSTANCE instance) : instance_(instance), apartment_()
{
    core::Ensure(apartment_.Result(), "CoInitializeEx");

    mutex_ = CreateMutexW(nullptr, TRUE, L"WebViewDA.Voice.SingleInstance");
    if (mutex_ == nullptr)
    {
        throw std::runtime_error("CreateMutexW failed.");
    }
    alreadyRunning_ = GetLastError() == ERROR_ALREADY_EXISTS;
}

Application::~Application()
{
    if (mutex_ != nullptr)
    {
        if (!alreadyRunning_)
        {
            ReleaseMutex(mutex_);
        }
        CloseHandle(mutex_);
    }
}

int Application::Run(int showCommand)
{
    if (alreadyRunning_)
    {
        return 0;
    }

    platform::windows::Window window(instance_);
    window.Create();
    window.Show(showCommand);

    MSG message{};
    while (true)
    {
        const BOOL result = GetMessageW(&message, nullptr, 0, 0);
        if (result == -1)
        {
            throw std::runtime_error("GetMessageW failed.");
        }

        if (result == 0)
        {
            return static_cast<int>(message.wParam);
        }

        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
}
}
