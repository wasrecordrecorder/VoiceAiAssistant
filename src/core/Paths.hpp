#pragma once

#include <filesystem>

namespace webviewda::core
{
class Paths final
{
public:
    static std::filesystem::path ExecutableDirectory();
    static std::filesystem::path AssetsDirectory();
    static std::filesystem::path BackendDirectory();
    static std::filesystem::path DataDirectory();
    static std::filesystem::path UserDataDirectory();
};
}
