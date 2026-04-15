'Private Sub Workbook_Open() ' chay 1 MAC
    'Dim myMAC As String
    'Dim allowedMAC As String
    'myMAC = GetMACAddress()
    ' Đây là d?a ch? MAC b?n mu?n cho phép (hăy thay d?i dúng theo máy c?n khóa)
    'allowedMAC = "A8:A1:59:1E:CA:08"   ' <-- S?a thành MAC c?a b?n
    'MsgBox "Ma MAC may tinh cua ban la" & myMAC
    
    
    'If myMAC <> allowedMAC Then
        'MsgBox "Ban không có quyen su dung file này!", vbCritical
        'ThisWorkbook.Close SaveChanges:=False
    'End If
'End Sub

Private Sub Workbook_Open() ' chay nhieu MAC
    Dim myMAC As String
    Dim allowedMACs As Variant
    Dim i As Integer
    Dim isAllowed As Boolean
    
    myMAC = GetMACAddress()
    'MsgBox "MAC máy b?n dang dùng: " & myMAC   ' <-- Debug hi?n MAC th?t
    
    'Danh sách các MAC du?c phép
    allowedMACs = Array("A8:A1:59:1E:CA:08", "60:CF:84:7B:84:4F", "34:5A:60:75:E3:30", "30:56:0F:14:8D:CF") ' <-- S?a danh sách này theo ư b?n
    
    isAllowed = False
    For i = LBound(allowedMACs) To UBound(allowedMACs)
        If Trim(UCase(myMAC)) = Trim(UCase(allowedMACs(i))) Then
            isAllowed = True
            Exit For
        End If
    Next i
    
    If Not isAllowed Then
        MsgBox "Ban không có quyen su dung file này!", vbCritical
        ThisWorkbook.Close SaveChanges:=False
    End If
End Sub



Private Sub Workbook_SheetSelectionChange(ByVal Sh As Object, ByVal Target As Range)
    Dim FirstPageLastRow As Long
    FirstPageLastRow = 76  ' Trang d?u h?t ? ḍng 76

    ' N?u ch?n trong trang 1 ? Zoom 90% (ho?c 99%)
    If Target.row <= FirstPageLastRow Then
        If ActiveWindow.Zoom <> 90 Then ActiveWindow.Zoom = 90
    Else
        ' N?u ch?n trong trang 2 tr? di ? Zoom 100%
        If ActiveWindow.Zoom <> 100 Then ActiveWindow.Zoom = 100
    End If
End Sub
