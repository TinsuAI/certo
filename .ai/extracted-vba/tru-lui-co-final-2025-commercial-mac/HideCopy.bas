Sub HideRowsXuat()
    Dim ws As Worksheet
    Dim lastRow As Long
    Dim i As Long
    Dim hasHiddenRows As Boolean
    Dim toggleState As String ' Dùng bien Toggle de ghi nho trang thái
    
    Application.ScreenUpdating = False ' ngung update man hinh
    Application.DisplayAlerts = False ' ko canh bao
    Application.EnableEvents = False ' ngung su kien
    Application.Calculation = xlCalculationManual ' ngung tinh toan excel

    Set ws = ThisWorkbook.Sheets("Xuat")
    lastRow = ws.Cells(ws.Rows.Count, "B").End(xlUp).row
   ' Đoc trang thái tai ô C1
    toggleState = ws.Range("C1").Value

   If toggleState <> "hidden" Then ' Trang thái hien tai là chua ân => tiên hành ân
       
        For i = 1 To lastRow
            If ws.Cells(i, "B").Value = 0 Then
                ws.Rows(i).Hidden = True
            End If
        Next i
        ' Ghi l?i tr?ng thái dă ?n
        ws.Range("C1").Value = "hidden"
    Else
        ' Tr?ng thái hi?n t?i là dă ?n ? ti?n hành b? ?n
        ws.Rows.Hidden = False
        ' Ghi l?i tr?ng thái dă b? ?n
        ws.Range("C1").Value = ""
    End If
    
    
    
lbFinally:    ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
    
    
End Sub


Sub copyXuat()
        Dim ws As Worksheet
        Dim lastRow As Long, lastRow1 As Double, lastRow2 As Long
        Dim i As Long
        Dim rng As Range
        Dim countRange As Range
        Dim wsNK2 As Worksheet, wsXN As Worksheet
    Application.ScreenUpdating = False ' ngung update man hinh
    Application.DisplayAlerts = False ' ko canh bao
    'Application.EnableEvents = False ' ngung su kien
    Application.Calculation = xlCalculationManual ' ngung tinh toan excel
        
    Set wsXN = ThisWorkbook.Sheets("X-N")
    Set wsNK2 = ThisWorkbook.Sheets("NK2")
    Set ws = ThisWorkbook.Sheets("Xuat")
    
    '  hiên toàn bô du lieu bo an do loc
    If ws.FilterMode Then ' bat buoc dung if neu ko se bi loi
        ws.ShowAllData
    End If
    
    ' Tat hoàn toàn che do AutoFilter
    If ws.AutoFilterMode Then
        ws.AutoFilterMode = False
    End If
    
  'copy data tu sheet Xuat sang sheet X-N
  lastRow = ws.Cells(ws.Rows.Count, "A").End(xlUp).row
    With ws.Range("A2:B" & lastRow)
        .AutoFilter Field:=2, criteria1:=">0" 'Field:=2 là côt thu 2 trong pham vi).
        On Error Resume Next ' Tránh loi nêu không có ô nào visible
        Set rng = Intersect(.Offset(1), .Resize(.Rows.Count), .SpecialCells(xlCellTypeVisible))
        If Not rng Is Nothing Then
            rng.Activate
            rng.Select
            rng.Copy
            wsXN.Range("S4").PasteSpecial xlPasteValues
        Else
            MsgBox "Không có data copy!", vbInformation
        End If
    End With
    
    ' t́m countif o NK2 de loc mă
    lastRow1 = wsNK2.Cells(wsNK2.Rows.Count, "E").End(xlUp).row
    lastRow2 = wsXN.Cells(wsXN.Rows.Count, "S").End(xlUp).row
    Set countRange = wsXN.Range("S4:S" & lastRow2)
        For i = 5 To lastRow1
            wsNK2.Range("S" & i).Value = Application.WorksheetFunction.CountIf(countRange, wsNK2.Range("E" & i).Value)
        Next i
        
        
     

lbFinally:    ' hoan tra ve ban dau
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic


End Sub

Sub update()

    Dim i As Long, lastRowDM As Long, lastRowXuat As Long
    Dim wsDM As Worksheet, wsXuat As Worksheet
    Dim lookupRangeXuat As Range, result As Range
    Dim ref As Variant
    
    Set wsDM = ThisWorkbook.Sheets("DM")
    Set wsXuat = ThisWorkbook.Sheets("Xuat")
    
    lastRowDM = wsDM.Cells(wsDM.Rows.Count, "F").End(xlUp).row
    lastRowXuat = wsXuat.Cells(wsXuat.Rows.Count, "A").End(xlUp).row
    
    Set lookupRangeXuat = wsXuat.Range("A3:A" & lastRowXuat + 2)
    Set ref = Nothing
    Application.ScreenUpdating = False ' ngung update man hinh
    Application.DisplayAlerts = False ' ko canh bao
    Application.EnableEvents = False ' ngung su kien
    Application.Calculation = xlCalculationManual ' ngung tinh toan excel
    
    '  hiên toàn bô du lieu bo an do loc
    If wsXuat.FilterMode Then ' bat buoc dung if neu ko se bi loi
        wsXuat.ShowAllData
    End If
    
    
    ' thêm mă moi tu DM sang Xuat
        For i = 7 To lastRowDM
            ref = wsDM.Range("F" & i).Value ' tham sô
            Set result = lookupRangeXuat.Find(What:=ref, LookIn:=xlValues, LookAt:=xlWhole) ' ham vlookup
            
            If ref <> "" Then ' bây lôi
                If result Is Nothing Then
                    lastRowXuat = lastRowXuat + 1
                    wsXuat.Range("A" & lastRowXuat) = ref
                    'wsXuat.Range("B" & lastRowXuat).Formula = wsXuat.Range("B3").Formula
                End If
            End If
        Next i
    
     ' Sap xep tu A den Z
        ActiveWorkbook.Worksheets("Xuat").AutoFilter.Sort.SortFields.Clear
        ActiveWorkbook.Worksheets("Xuat").AutoFilter.Sort.SortFields.Add key:=Range( _
            "A2"), SortOn:=xlSortOnValues, Order:=xlAscending, DataOption:= _
            xlSortNormal
        With ActiveWorkbook.Worksheets("Xuat").AutoFilter.Sort
            .Header = xlYes
            .MatchCase = False
            .Orientation = xlTopToBottom
            .SortMethod = xlPinYin
            .Apply
        End With
        
    'tính sô luong sumif côt B
        Dim sumRange As Range, lookupRange As Range
        Set lookupRange = wsDM.Range("F7:F" & lastRowDM)
        Set sumRange = wsDM.Range("K7:K" & lastRowDM)
           For i = 3 To lastRowXuat
               wsXuat.Range("B" & i) = Application.SumIf(lookupRange, wsXuat.Range("A" & i), sumRange)
           Next i
        
    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic
    
    
End Sub

Sub updateArr()

    Dim wsDM As Worksheet, wsXuat As Worksheet
    Dim arrDM As Variant, arrXuat As Variant
    Dim dictXuat As Object
    Dim i As Long, lastRowDM As Long, lastRowXuat As Long
    Dim ref As Variant
    Dim outputRows As Long
    
    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual

    Set wsDM = ThisWorkbook.Sheets("DM")
    Set wsXuat = ThisWorkbook.Sheets("Xuat")
    Set dictXuat = CreateObject("Scripting.Dictionary")

    ' L?y d? li?u DM vào m?ng
    lastRowDM = wsDM.Cells(wsDM.Rows.Count, "F").End(xlUp).row
    arrDM = wsDM.Range("F7:F" & lastRowDM).Value
    lastRowXuat = wsXuat.Cells(wsXuat.Rows.Count, "A").End(xlUp).row
    
    '  hiên toàn bô du lieu bo an do loc
    If wsXuat.FilterMode Then ' bat buoc dung if neu ko se bi loi
        wsXuat.ShowAllData
    End If
    
    
    ' L?y d? li?u hi?n có trong c?t A sheet Xuat vào dictionary
    If lastRowXuat >= 3 Then
        arrXuat = wsXuat.Range("A3:A" & lastRowXuat).Value
        For i = 1 To UBound(arrXuat, 1)
            If Not IsEmpty(arrXuat(i, 1)) Then
                dictXuat(arrXuat(i, 1)) = 1
            End If
        Next i
    End If

    ' T́m và thêm mă m?i t? DM
    outputRows = 0
    For i = 1 To UBound(arrDM, 1)
        ref = arrDM(i, 1)
        If Trim(ref) <> "" Then
            If Not dictXuat.Exists(ref) Then
                lastRowXuat = lastRowXuat + 1
                wsXuat.Range("A" & lastRowXuat).Value = ref
                ' N?u mu?n copy công th?c t? B3 xu?ng:
                ' wsXuat.Range("B" & lastRowXuat).Formula = wsXuat.Range("B3").Formula
                dictXuat(ref) = 1 ' Đánh d?u dă thêm
                outputRows = outputRows + 1
            End If
        End If
    Next i
    
    
    ' Sap xep tu A den Z
        ActiveWorkbook.Worksheets("Xuat").AutoFilter.Sort.SortFields.Clear
        ActiveWorkbook.Worksheets("Xuat").AutoFilter.Sort.SortFields.Add key:=Range( _
            "A2"), SortOn:=xlSortOnValues, Order:=xlAscending, DataOption:= _
            xlSortNormal
        With ActiveWorkbook.Worksheets("Xuat").AutoFilter.Sort
            .Header = xlYes
            .MatchCase = False
            .Orientation = xlTopToBottom
            .SortMethod = xlPinYin
            .Apply
        End With

    'tính sô luong sumif côt B
        Dim sumRange As Range, lookupRange As Range
        Set lookupRange = wsDM.Range("F7:F" & lastRowDM)
        Set sumRange = wsDM.Range("K7:K" & lastRowDM)
           For i = 3 To lastRowXuat
               wsXuat.Range("B" & i) = Application.SumIf(lookupRange, wsXuat.Range("A" & i), sumRange)
           Next i


    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic

End Sub
