#include "platform/windows/ComApartment.hpp"

namespace webviewda::platform::windows
{
ComApartment::ComApartment(DWORD flags) : result_(CoInitializeEx(nullptr, flags))
{
}

ComApartment::~ComApartment()
{
    if (SUCCEEDED(result_))
    {
        CoUninitialize();
    }
}

HRESULT ComApartment::Result() const noexcept
{
    return result_;
}

bool ComApartment::Ready() const noexcept
{
    return SUCCEEDED(result_);
}
}
