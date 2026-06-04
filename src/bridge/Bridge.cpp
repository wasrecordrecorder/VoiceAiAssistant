#include "bridge/Bridge.hpp"

#include "core/BuildInfo.hpp"
#include "core/Result.hpp"
#include "core/Utf.hpp"
#include "platform/windows/TrayIcon.hpp"
#include "platform/windows/AppMessages.hpp"

#include <nlohmann/json.hpp>
#include <shellapi.h>

#include <stdexcept>
#include <string>
#include <utility>

namespace webviewda::bridge
{
using Microsoft::WRL::Callback;
using nlohmann::json;

Bridge::Bridge(HWND window, Microsoft::WRL::ComPtr<ICoreWebView2> webView, backend::BackendConnection connection) :
    window_(window), webView_(std::move(webView)), connection_(std::move(connection))
{
}

Bridge::~Bridge()
{
    if (attached_ && webView_)
    {
        webView_->remove_WebMessageReceived(token_);
    }
}

void Bridge::Attach()
{
    const HRESULT result = webView_->add_WebMessageReceived(
        Callback<ICoreWebView2WebMessageReceivedEventHandler>(
            [this](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* arguments) -> HRESULT
            {
                Receive(arguments);
                return S_OK;
            })
            .Get(),
        &token_);

    core::Ensure(result, "add_WebMessageReceived");
    attached_ = true;
}

void Bridge::Receive(ICoreWebView2WebMessageReceivedEventArgs* arguments)
{
    LPWSTR sourceValue = nullptr;
    if (FAILED(arguments->get_Source(&sourceValue)) || sourceValue == nullptr)
    {
        return;
    }

    const std::wstring source(sourceValue);
    CoTaskMemFree(sourceValue);

    if (!source.starts_with(L"https://app.local/"))
    {
        return;
    }

    LPWSTR messageValue = nullptr;
    if (FAILED(arguments->TryGetWebMessageAsString(&messageValue)) || messageValue == nullptr)
    {
        return;
    }

    const std::wstring message(messageValue);
    CoTaskMemFree(messageValue);

    try
    {
        Dispatch(message);
    }
    catch (const std::exception& error)
    {
        try
        {
            SendError(error.what());
        }
        catch (...)
        {
        }
    }
}

void Bridge::Dispatch(std::wstring_view payload)
{
    const json request = json::parse(core::ToUtf8(payload));
    const std::string command = request.value("command", "");

    if (command == "app.ready")
    {
        LPWSTR runtimeValue = nullptr;
        std::string runtime = "unavailable";

        if (SUCCEEDED(GetAvailableCoreWebView2BrowserVersionString(nullptr, &runtimeValue)) && runtimeValue != nullptr)
        {
            runtime = core::ToUtf8(runtimeValue);
            CoTaskMemFree(runtimeValue);
        }

        Send(
            "app.info",
            {
                {"name", std::string(core::ProductName)},
                {"version", std::string(core::ProductVersion)},
                {"runtime", runtime},
                {"backend", {
                    {"online", connection_.online},
                    {"url", connection_.websocketUrl},
                    {"token", connection_.token},
                    {"error", connection_.error}
                }}
            });
        return;
    }

    if (command == "window.drag")
    {
        ReleaseCapture();
        SendMessageW(window_, WM_NCLBUTTONDOWN, HTCAPTION, 0);
        return;
    }

    if (command == "window.minimize")
    {
        ShowWindow(window_, SW_MINIMIZE);
        return;
    }

    if (command == "window.maximize")
    {
        ShowWindow(window_, IsZoomed(window_) ? SW_RESTORE : SW_MAXIMIZE);
        return;
    }

    if (command == "window.close")
    {
        PostMessageW(window_, WM_CLOSE, 0, 0);
        return;
    }

    if (command == "window.restoreMain")
    {
        PostMessageW(window_, platform::windows::RestoreMainMessage, 0, 0);
        return;
    }

    if (command == "ptt.configure")
    {
        const auto settings = request.value("payload", json::object());
        const bool enabled = settings.value("enabled", false);
        const UINT virtualKey = static_cast<UINT>(settings.value("keyCode", static_cast<int>(VK_F8)));
        const UINT modifiers = static_cast<UINT>(settings.value("modifiers", 0));
        const LPARAM configuration = static_cast<LPARAM>((modifiers << 8) | (enabled ? 1U : 0U));
        PostMessageW(window_, platform::windows::ConfigurePushToTalkMessage, static_cast<WPARAM>(virtualKey), configuration);
        return;
    }

    if (command == "widget.update")
    {
        const auto value = request.value("payload", json::object()).dump();
        COPYDATASTRUCT data{};
        data.dwData = platform::windows::WidgetStatusCopyData;
        data.cbData = static_cast<DWORD>(value.size());
        data.lpData = const_cast<char*>(value.data());
        SendMessageW(window_, WM_COPYDATA, 0, reinterpret_cast<LPARAM>(&data));
        return;
    }

    if (command == "widget.configure")
    {
        const auto settings = request.value("payload", json::object());
        const bool enabled = settings.value("enabled", true);
        const std::string orientation = settings.value("orientation", std::string("horizontal"));
        PostMessageW(window_, platform::windows::ConfigureWidgetMessage, enabled ? 1 : 0, orientation == "vertical" ? 1 : 0);
        return;
    }

    if (command == "app.quit")
    {
        PostMessageW(window_, WM_COMMAND, platform::windows::TrayIcon::ExitCommand, 0);
        return;
    }

    throw std::runtime_error("Unknown native command.");
}

void Bridge::PostEvent(std::string_view event, const json& payload)
{
    Send(event, payload);
}

void Bridge::Send(std::string_view event, const json& payload)
{
    const json response = {{"event", event}, {"payload", payload}};
    const auto message = core::FromUtf8(response.dump());
    core::Ensure(webView_->PostWebMessageAsJson(message.c_str()), "PostWebMessageAsJson");
}

void Bridge::SendError(std::string_view message)
{
    Send("native.error", {{"message", message}});
}
}
