Function GetMACAddress() As String
    Dim objWMIService As Object
    Dim colItems As Object
    Dim objItem As Object
    Dim strMAC As String
    
    ' K?t n?i t?i WMI
    Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
    Set colItems = objWMIService.ExecQuery("Select * from Win32_NetworkAdapterConfiguration Where IPEnabled = True")
    
    ' L?y MAC Address d?u tiên t́m th?y
    For Each objItem In colItems
        strMAC = objItem.MACAddress
        Exit For
    Next
    
    GetMACAddress = strMAC
End Function
