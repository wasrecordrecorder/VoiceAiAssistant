#pragma once

#include <Windows.h>
#include <objbase.h>

namespace webviewda::platform::windows
{
class ComApartment final
{
public:
    explicit ComApartment(DWORD flags = COINIT_APARTMENTTHREADED);
    ~ComApartment();

    ComApartment(const ComApartment&) = delete;
    ComApartment& operator=(const ComApartment&) = delete;

    HRESULT Result() const noexcept;
    bool Ready() const noexcept;

private:
    HRESULT result_;
};
}
