Option Explicit
Sub tachDong1()
unProtected
    Dim i, j, k, lastRow, lastRow2 As Long
    With ThisWorkbook.Sheets("X-N")
    lastRow = ThisWorkbook.Sheets("X-N").Cells(.Rows.Count, "E").End(xlUp).row
    lastRow2 = ThisWorkbook.Sheets("XK").Cells(.Rows.Count, "B").End(xlUp).row
    ' code vba chay muot hon
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
' tach dong
        For i = 4 To lastRow
        k = i + 1
            If .Range("S" & i).Value <> .Range("E" & i).Value Then
                .Range(.Cells(i, 19), .Cells(lastRow, 20)).Copy ' copy tu ḍng i cot 12 den ḍng cuoi côt 20
                .Cells(k, 19).PasteSpecial Paste:=xlPasteValues ' paste ra duoi 1 ḍng
                .Range("S" & i).Value = .Range("E" & i) ' cho cot ma = nhau
                .Range("T" & i).Value = "0" ' sl = 0
             End If
        Next i
        Application.CutCopyMode = False
        
  'tinh sl su dung
        For j = 4 To lastRow
            If .Range("K" & j) > .Range("T" & j) Then ' néu sl ton > sl cân xuat & ma cot E4 # E3
                .Range("V" & j) = .Range("T" & j) ' sl xuat = sl can su dung
            ElseIf .Range("K" & j) = .Range("T" & j) Then ' néu sl tôn = sl cân xuat
                .Range("V" & j) = .Range("K" & j) ' sl xuat = sl tôn
            ElseIf .Range("K" & j) < .Range("T" & j) Then ' néu sl tôn < sl cân xuat
                .Range("V" & j) = .Range("K" & j) ' sl xuat = sl tôn
                .Range("T" & j + 1) = .Range("T" & j) - .Range("V" & j) 'tính sl c̣n lai o ḍng lien ke
            End If
            .Range("R" & j).Value = ThisWorkbook.Sheets("DM").Cells(6, "K")
        Next j
        
         ' to mau truong hop loai hinh B11-E31
       .Range("C1") = Application.WorksheetFunction.VLookup(.Range("R4"), _
       ThisWorkbook.Sheets("XK").Range("B11:D" & lastRow2), 3, 0)
        If .Range("C1") <> "E62" Then
            For i = 4 To lastRow
                If .Range("C" & i) = "E31" Then
                    .Range("C" & i).Font.ColorIndex = 2 'chu mau trang
                    .Range("C" & i).Interior.Color = RGB(38, 4, 242) ' mau xanh
                End If
            Next
        End If
lbFinally:    ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
    End With
 protected
End Sub


Sub tachDong2()
    unProtected
    
    ' Khai báo bi?n
    Dim wsSource As Worksheet, wsXK As Worksheet, wsDM As Worksheet
    Dim arrData As Variant
    Dim lastRow As Long, lastRow2 As Long
    Dim i As Long, j As Long, k As Long
    Dim lookupValue As Variant

    ' Gán sheet d? làm vi?c
    Set wsSource = ThisWorkbook.Sheets("X-N")
    Set wsXK = ThisWorkbook.Sheets("XK")
    Set wsDM = ThisWorkbook.Sheets("DM")
    
    ' T?i uu t?c d? x? lư
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual
    
    ' Xác d?nh ḍng cu?i cùng
    lastRow = wsSource.Cells(wsSource.Rows.Count, "E").End(xlUp).row
    lastRow2 = wsXK.Cells(wsXK.Rows.Count, "B").End(xlUp).row
    
    ' Load du lieu vào mang tu A4:Z(lastRow)
    arrData = wsSource.Range("A4:Z" & lastRow).Value

    ' Bat dau xu lư du lieu trong mang - Tách ḍng n?u S khác E
    i = 1
   ' duyet mang
   ' UBound(arr) tra ve chi so lon nhat trong mang (Upper Bound).
   ' LBound(arr) tra ve chi so nho nhat trong mang (Lower Bound).
    Do While i <= UBound(arrData, 1)
        If arrData(i, 19) <> arrData(i, 5) Then ' N?u S khác E
            ' D?ch t? ḍng cu?i lên 1 ḍng
            For k = UBound(arrData, 1) To i Step -1
                If k + 1 <= UBound(arrData, 1) Then
                    arrData(k + 1, 19) = arrData(k, 19) ' Copy c?t S
                    arrData(k + 1, 20) = arrData(k, 20) ' Copy c?t T
                End If
            Next k
            ' Sau khi d?ch xong, gán l?i giá tr?
            arrData(i, 19) = arrData(i, 5) ' S = E
            arrData(i, 20) = 0 ' T = 0
            lastRow = lastRow + 1 ' C?p nh?t l?i lastRow
        End If
        i = i + 1
    Loop

    ' Tính toán lu?ng s? d?ng V
    For j = 1 To UBound(arrData, 1)
        If j = 1 Then
            ' Ḍng d?u tiên, không so sánh v?i ḍng tru?c
            If arrData(j, 11) > arrData(j, 20) Then
                arrData(j, 22) = arrData(j, 20)
            Else
                arrData(j, 22) = arrData(j, 11)
                If j < UBound(arrData, 1) Then
                    arrData(j + 1, 20) = arrData(j, 20) - arrData(j, 22)
                End If
            End If
        Else
            ' Các ḍng t? ḍng 2 tr? di
            If arrData(j, 11) > arrData(j, 20) And arrData(j, 5) <> arrData(j - 1, 5) Then
                arrData(j, 22) = arrData(j, 20)
            ElseIf arrData(j, 11) > arrData(j, 20) And arrData(j, 5) = arrData(j - 1, 5) Then
                arrData(j, 22) = arrData(j, 20)
            ElseIf arrData(j, 11) <= arrData(j, 20) Then
                arrData(j, 22) = arrData(j, 11)
                If j < UBound(arrData, 1) Then
                    arrData(j + 1, 20) = arrData(j, 20) - arrData(j, 22)
                End If
            End If
        End If
        
        ' Gán giá tr? R (C?t 18) t? DM sheet
        arrData(j, 18) = wsDM.Cells(6, "K").Value
    Next j

    ' T́m lo?i h́nh d? xác d?nh có c?n tô màu không
    On Error Resume Next
    lookupValue = Application.VLookup(arrData(1, 18), wsXK.Range("B11:D" & lastRow2), 3, 0)
    On Error GoTo 0

    ' N?u t́m th?y và khác E62 th́ tô màu ḍng có C = "E31"
    If Not IsError(lookupValue) And lookupValue <> "E62" Then
        For i = 1 To UBound(arrData, 1)
            If arrData(i, 3) = "E31" Then
                With wsSource.Range("C" & i + 3)
                    .Font.ColorIndex = 2 ' ch? tr?ng
                    .Interior.Color = RGB(38, 4, 242) ' n?n xanh
                End With
            End If
        Next i
    End If

    ' Ghi du lieu tu mang arrData vào lai sheet
    wsSource.Range("A4").Resize(UBound(arrData, 1), UBound(arrData, 2)).Value = arrData
    
     'xoá côt U di
    Dim lastRow3 As Long
    lastRow3 = wsSource.Cells(wsSource.Rows.Count, "U").End(xlUp).row
    wsSource.Range("U4:U" & lastRow3) = ""

lbFinally:
    ' Khôi ph?c l?i các thi?t l?p ban d?u
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
    
    protected
End Sub





Sub tachDongArr()
    unProtected
    
    ' Khai báo bi?n
    Dim wsSource As Worksheet, wsXK As Worksheet, wsDM As Worksheet
    Dim arrData As Variant
    Dim lastRow As Long, lastRow2 As Long, lastRow3 As Long
    Dim i As Long, j As Long, k As Long, m As Long
    Dim lookupValue As Variant

    ' Gán sheet d? làm vi?c
    Set wsSource = ThisWorkbook.Sheets("X-N")
    Set wsXK = ThisWorkbook.Sheets("XK")
    Set wsDM = ThisWorkbook.Sheets("DM")
    
    ' T?i uu t?c d? x? lư
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual
    
    ' Xác d?nh ḍng cu?i cùng
    lastRow = wsSource.Cells(wsSource.Rows.Count, "E").End(xlUp).row
    lastRow2 = wsXK.Cells(wsXK.Rows.Count, "B").End(xlUp).row
    lastRow3 = wsSource.Cells(wsSource.Rows.Count, "T").End(xlUp).row
    
    ' Load du lieu vào mang tu A4:Z(lastRow)
    arrData = wsSource.Range("A4:Z" & lastRow).Value

    ' Bat dau xu lư du lieu trong mang - Tách ḍng n?u S khác E
    Dim flag As Boolean ' tao bien flag de dánh dâu
    flag = False
    m = 4
  Do While m <= lastRow3
    If wsSource.Range("T" & m).Value = wsSource.Range("U" & m).Value Then
    flag = True ' Đă gap truong hop T = U
        ' Case 1 : tôn = sl cân xuât
        For i = 4 To lastRow
        k = i + 1
            If wsSource.Range("S" & i).Value <> wsSource.Range("E" & i).Value Then
                wsSource.Range(wsSource.Cells(i, 19), wsSource.Cells(lastRow, 20)).Copy
                wsSource.Cells(k, 19).PasteSpecial Paste:=xlPasteValues
                wsSource.Range("S" & i).Value = wsSource.Range("E" & i) ' cho cot ma = nhau
                wsSource.Range("T" & i).Value = "0" ' sl = 0
             End If
        
        Next i
        Application.CutCopyMode = False
        
          'tinh sl su dung
        For j = 4 To lastRow
            If wsSource.Range("K" & j) > wsSource.Range("T" & j) Then ' néu sl ton > sl cân xuat & ma cot E4 # E3
                wsSource.Range("V" & j) = wsSource.Range("T" & j) ' sl xuat = sl can su dung
            ElseIf wsSource.Range("K" & j) = wsSource.Range("T" & j) Then ' néu sl tôn = sl cân xuat
                wsSource.Range("V" & j) = wsSource.Range("K" & j) ' sl xuat = sl tôn
            ElseIf wsSource.Range("K" & j) < wsSource.Range("T" & j) Then ' néu sl tôn < sl cân xuat
                wsSource.Range("V" & j) = wsSource.Range("K" & j) ' sl xuat = sl tôn
                wsSource.Range("T" & j + 1) = wsSource.Range("T" & j) - wsSource.Range("V" & j) 'tính sl c̣n lai o ḍng lien ke
            End If
            wsSource.Range("R" & j).Value = ThisWorkbook.Sheets("DM").Cells(6, "K")
        Next j
        
        Exit Do ' thoát khoi ṿng lap
        
    End If
    m = m + 1
  Loop ' kêt thúc flag = true
  
  
   ' Neu không hê có ḍng nào T = U th́ xu lư riêng  dây <=> flag = false
        If Not flag Then ' nêu không t́m thây T=U th́
        ' Case 2 : tôn > sl cân xuât
             i = 1
            ' duyet mang
            ' UBound(arr) tra ve chi so lon nhat trong mang (Upper Bound).
            ' LBound(arr) tra ve chi so nho nhat trong mang (Lower Bound).
             Do While i <= UBound(arrData, 1)
                 If arrData(i, 19) <> arrData(i, 5) Then ' Nêu S khác E
                     ' Dich tu ḍng cuôi lên 1 ḍng
                     For k = UBound(arrData, 1) To i Step -1
                         If k + 1 <= UBound(arrData, 1) Then
                             arrData(k + 1, 19) = arrData(k, 19) ' Copy c?t S
                             arrData(k + 1, 20) = arrData(k, 20) ' Copy c?t T
                         End If
                     Next k
                     ' Sau khi d?ch xong, gán lai giá tri
                     arrData(i, 19) = arrData(i, 5) ' S = E
                     arrData(i, 20) = 0 ' T = 0
                     lastRow = lastRow + 1 ' C?p nh?t l?i lastRow
                 End If
                 i = i + 1
             Loop
             
            ' Tính toán luong su dung côt V
            For j = 1 To UBound(arrData, 1)
                If j = 1 Then
                    ' Ḍng dâu tiên, không so sánh voi ḍng truoc
                    If arrData(j, 11) > arrData(j, 20) Then
                        arrData(j, 22) = arrData(j, 20)
                    Else
                        arrData(j, 22) = arrData(j, 11)
                        If j < UBound(arrData, 1) Then
                            arrData(j + 1, 20) = arrData(j, 20) - arrData(j, 22)
                        End If
                    End If
                Else
                    ' Các ḍng t? ḍng 2 tr? di
                    If arrData(j, 11) > arrData(j, 20) And arrData(j, 5) <> arrData(j - 1, 5) Then
                        arrData(j, 22) = arrData(j, 20)
                    ElseIf arrData(j, 11) > arrData(j, 20) And arrData(j, 5) = arrData(j - 1, 5) Then
                        arrData(j, 22) = arrData(j, 20)
                    ElseIf arrData(j, 11) <= arrData(j, 20) Then
                        arrData(j, 22) = arrData(j, 11)
                        If j < UBound(arrData, 1) Then
                            arrData(j + 1, 20) = arrData(j, 20) - arrData(j, 22)
                        End If
                    End If
                End If
                
                ' Gán giá tri R (Côt 18) tu DM sheet
                arrData(j, 18) = wsDM.Cells(6, "K").Value
            Next j
            
            ' Ghi du lieu tu mang arrData vào lai sheet
            wsSource.Range("A4").Resize(UBound(arrData, 1), UBound(arrData, 2)).Value = arrData
        End If ' end flag

    ' T́m loai h́nh dê xác dinh có cân tô màu không
    On Error Resume Next
    lookupValue = Application.VLookup(arrData(1, 18), wsXK.Range("B11:D" & lastRow2), 3, 0)
    On Error GoTo 0

    ' Nêu t́m thây và khác E62 th́ tô màu ḍng có C = "E31"
    If Not IsError(lookupValue) Then
        If lookupValue <> "E62" Then
            For i = 1 To UBound(arrData, 1)
                If arrData(i, 3) = "E31" Then
                    With wsSource.Range("C" & i + 3)
                        .Font.ColorIndex = 2 ' ch? tr?ng
                        .Interior.Color = RGB(38, 4, 242) ' n?n xanh
                    End With
                End If
            Next i
        End If
    End If
        
 

     'xoá côt U di
    Dim lastRow4 As Long
    lastRow4 = wsSource.Cells(wsSource.Rows.Count, "U").End(xlUp).row
    wsSource.Range("U4:U" & lastRow4) = ""

lbFinally:
    ' Khôi ph?c l?i các thi?t l?p ban d?u
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
    
    protected
End Sub






Sub deleteXN()
Dim lastRow, lastCol As Long
With ThisWorkbook.Sheets("X-N")
lastRow = .Cells(.Rows.Count, "E").End(xlUp).row
lastCol = .Cells(6, Columns.Count).End(xlToLeft).Column
unProtected
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
    
        .Range("A4:V" & lastRow + 3).ClearContents
        .Range("C1").ClearContents
        .Range("S1").ClearContents

Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
protected
End With
End Sub
