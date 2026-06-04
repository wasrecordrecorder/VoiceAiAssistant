#include "core/Paths.hpp"

#include <Windows.h>
#include <ShlObj.h>

#include <array>
#include <stdexcept>

namespace webviewda::core
{
std::filesystem::path Paths::ExecutableDirectory()
{
    std::array<wchar_t, 32768> path{};
    const DWORD length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
    if (length == 0 || length >= static_cast<DWORD>(path.size()))
    {
        throw std::runtime_error("GetModuleFileNameW failed.");
    }

    return std::filesystem::path(std::wstring_view(path.data(), length)).parent_path();
}

std::filesystem::path Paths::AssetsDirectory()
{
    return ExecutableDirectory() / L"assets";
}

std::filesystem::path Paths::BackendDirectory()
{
    return ExecutableDirectory() / L"backend";
}

std::filesystem::path Paths::DataDirectory()
{
    PWSTR localAppData = nullptr;
    const HRESULT result = SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DEFAULT, nullptr, &localAppData);
    if (FAILED(result) || localAppData == nullptr)
    {
        throw std::runtime_error("SHGetKnownFolderPath failed.");
    }

    const std::filesystem::path path = std::filesystem::path(localAppData) / L"WebViewDA";
    CoTaskMemFree(localAppData);
    return path;
}

std::filesystem::path Paths::UserDataDirectory()
{
    return DataDirectory() / L"WebView2";
}
}
