Sub locMa()
Attribute locMa.VB_ProcData.VB_Invoke_Func = " \n14"

   Call unProtected
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

    Sheets("NK2").Range("A4:S999999").AdvancedFilter Action:=xlFilterCopy, _
        CriteriaRange:=Range("W1:X2"), CopyToRange:=Range("A3:Q3"), Unique:=False
        
        
        
     Call AtoZArr
        
Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
   Call protected
  
End Sub

Sub locMaArr()


  Call unProtected

    Application.ScreenUpdating = False
    Application.DisplayAlerts = False
    Application.EnableEvents = False
    Application.Calculation = xlCalculationManual

    Dim wsSrc As Worksheet, wsDst As Worksheet
    Dim dataSrc As Variant, dataOut() As Variant
    Dim lastRowSrc As Long
    Dim i As Long, r As Long

    Set wsSrc = ThisWorkbook.Sheets("NK2")
    Set wsDst = ThisWorkbook.Sheets("X-N")

    lastRowSrc = wsSrc.Cells(wsSrc.Rows.Count, "B").End(xlUp).row

    ' Đ?c t? c?t A (1) d?n S (19) v́ dùng t?i c? c?t R (18) và S (19)
    dataSrc = wsSrc.Range("A5:S" & lastRowSrc).Value

    ReDim dataOut(1 To UBound(dataSrc, 1), 1 To 17) ' A:Q là 17 c?t

    r = 0
    For i = 1 To UBound(dataSrc, 1)
        ' C?t R = 18, S = 19 trong dataSrc
        If dataSrc(i, 19) = 1 And dataSrc(i, 18) > 0 Then
            r = r + 1
            ' A d?n Q là 1 d?n 17
            For j = 1 To 17
                dataOut(r, j) = dataSrc(i, j)
            Next j
            ' Ghi riêng c?t K (11) b?ng giá tr? c?t R (18)
            dataOut(r, 11) = dataSrc(i, 18)
        End If
    Next i

    If r > 0 Then
        wsDst.Range("A4").Resize(r, 17).Value = dataOut
    End If
    
    Call AtoZArr
    
    wsDst.Range("S1") = ThisWorkbook.Sheets("DM").Range("K6") ' de so sánh ngày tk
    

    Application.ScreenUpdating = True
    Application.DisplayAlerts = True
    Application.EnableEvents = True
    Application.Calculation = xlCalculationAutomatic

  Call protected

End Sub
Sub AtoZ()

Call unProtected
 
 Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel
 
    ActiveWorkbook.Worksheets("X-N").AutoFilter.Sort.SortFields.Clear
    ActiveWorkbook.Worksheets("X-N").AutoFilter.Sort.SortFields.Add key:=Range( _
        "E3"), SortOn:=xlSortOnValues, Order:=xlAscending, DataOption:= _
        xlSortNormal
    With ActiveWorkbook.Worksheets("X-N").AutoFilter.Sort
        .Header = xlYes
        .MatchCase = False
        .Orientation = xlTopToBottom
        .SortMethod = xlPinYin
        .Apply
    End With
    
    
    ' tính sumif de doi chieu sl
    Dim lastRow As Long, lastRow2 As Long, j As Long
    Dim ws As Worksheet
        Set ws = ThisWorkbook.Sheets("X-N")
        lastRow = ws.Cells(ws.Rows.Count, "E").End(xlUp).row
        lastRow2 = ws.Cells(ws.Rows.Count, "S").End(xlUp).row
        
    
        For j = 4 To lastRow2
            ws.Range("U" & j).Value = Application.WorksheetFunction.SumIf( _
                ws.Range("E4:E" & lastRow), ws.Range("S" & j), ws.Range("K4:K" & lastRow))
    
                ' Ki?m tra c? T và U d?u là so
                If IsNumeric(ws.Range("T" & j).Value) And IsNumeric(ws.Range("U" & j).Value) Then
                    If ws.Range("T" & j).Value > ws.Range("U" & j).Value Then
                        ws.Range("T" & j).Interior.Color = RGB(248, 253, 61) ' vàng
                    Else
                        ws.Range("T" & j).Interior.Color = RGB(255, 255, 255) ' tr?ng
                    End If
                Else
                    ' Có th? tô màu xám ho?c b? qua n?u không h?p l?
                    ws.Range("T" & j).Interior.Color = RGB(200, 200, 200)
                End If
        Next j
    
    
    
 Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
Call protected
End Sub

Sub AtoZArr()
    Dim ws As Worksheet
    Dim lastRow As Long
    Dim rng As Range
    Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel

    ' G¨¢n worksheet
    Set ws = ThisWorkbook.Sheets("X-N") ' Thay "X-N" n?u sheet kh¨¢c

    ' T¨¬m d¨°ng cu?i ? c?t E
    lastRow = ws.Cells(ws.Rows.Count, "E").End(xlUp).row

    ' Ki?m tra n?u ¨ªt d¨°ng th¨¬ b¨¢o l?i
    If lastRow < 4 Then
        MsgBox "Khong có  du lieu sap xep", vbExclamation
        Exit Sub
    End If

    ' X¨¢c ??nh v¨´ng d? li?u t? A4 ??n Q d¨°ng cu?i
    Set rng = ws.Range("A4:Q" & lastRow)

    ' X¨®a c¨¢c sort c? (n?u c¨®)
    ws.Sort.SortFields.Clear

    ' Th¨ºm ?i?u ki?n s?p x?p theo c?t E
    ws.Sort.SortFields.Add key:=ws.Range("E4:E" & lastRow), _
        SortOn:=xlSortOnValues, Order:=xlAscending, DataOption:=xlSortNormal

    ' ¨¢p d?ng s?p x?p to¨¤n v¨´ng A-Q
    With ws.Sort
        .SetRange rng
        .Header = xlNo ' Kh?ng c¨® ti¨ºu ?? trong v¨´ng A4:Q
        .MatchCase = False
        .Orientation = xlTopToBottom
        .SortMethod = xlPinYin ' S?p x?p theo t? ?i?n ti?ng Vi?t chu?n
        .Apply
    End With
    
     ' tính sumif de doi chieu sl
    Dim lastRow2 As Long, i As Long
        lastRow2 = ws.Cells(ws.Rows.Count, "S").End(xlUp).row
        
        For i = 4 To lastRow2
            ws.Range("U" & i).Value = Application.WorksheetFunction.SumIf( _
                ws.Range("E4:E" & lastRow), ws.Range("S" & i), ws.Range("K4:K" & lastRow))
    
                ' Ki?m tra c? T và U d?u là s?
                If IsNumeric(ws.Range("T" & i).Value) And IsNumeric(ws.Range("U" & i).Value) Then
                    If ws.Range("T" & i).Value > ws.Range("U" & i).Value Then
                        ws.Range("T" & i).Interior.Color = RGB(248, 253, 61) ' vàng
                    Else
                        ws.Range("T" & i).Interior.Color = RGB(255, 255, 255) ' tr?ng
                    End If
                Else
                    ' Có th? tô màu xám ho?c b? qua n?u không h?p l?
                    ws.Range("T" & i).Interior.Color = RGB(200, 200, 200)
                End If
        Next i
    
    

Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic

End Sub




Sub layDataNK()
Attribute layDataNK.VB_ProcData.VB_Invoke_Func = " \n14"
    
Call unProtected
' Loc ḍng 10 dên 65540
 Sheets("NK").Range("A10:BB65536").AdvancedFilter Action:=xlFilterCopy, _
        CopyToRange:=Range("A4:P4"), Unique:=False
    
 Call protected
End Sub


Sub layDataNKArr()

    Dim wsNK As Worksheet, wsNK2 As Worksheet
    Dim lastRowNK As Long, lastColNK As Long
    Dim lastColNK2 As Long
    Dim dataNK As Variant
    Dim headersNK As Variant, headersNK2 As Variant
    Dim output() As Variant
    Dim colMap() As Long
    Dim i As Long, j As Long, outRow As Long

    Set wsNK = ThisWorkbook.Sheets("NK")
    Set wsNK2 = ThisWorkbook.Sheets("NK2")

    ' Xác d?nh vùng d? li?u ngu?n
    lastRowNK = wsNK.Cells(wsNK.Rows.Count, "B").End(xlUp).row
    lastColNK = wsNK.Cells(10, wsNK.Columns.Count).End(xlToLeft).Column
    dataNK = wsNK.Range(wsNK.Cells(10, 1), wsNK.Cells(lastRowNK, lastColNK)).Value

    ' Xác d?nh vùng tiêu d? dích bên NK2 (ḍng 4)
    lastColNK2 = 16
    headersNK2 = wsNK2.Range(wsNK2.Cells(4, 1), wsNK2.Cells(4, lastColNK2)).Value
    headersNK = Application.Index(dataNK, 1, 0) ' hàng d?u tiên trong m?ng dataNK (tiêu d? NK)

 Call unProtected
Application.ScreenUpdating = False ' ngung update man hinh
Application.DisplayAlerts = False ' ko canh bao
Application.EnableEvents = False ' ngung su kien
Application.Calculation = xlCalculationManual ' ngung tinh toan excel


    ReDim colMap(1 To lastColNK2)
    
    ' Ḍ v? trí tiêu d? c?n copy t? NK vào m?ng colMap
    For j = 1 To lastColNK2
        colMap(j) = 0 ' m?c d?nh không t́m th?y
        For i = 1 To UBound(headersNK)
            If Trim(headersNK(i)) = Trim(headersNK2(1, j)) Then
                colMap(j) = i
                Exit For
            End If
        Next i
    Next j

    ' Kh?i t?o m?ng output v?i s? ḍng = s? ḍng d? li?u, s? c?t = s? c?t tiêu d? dích
    ReDim output(1 To lastRowNK - 10, 1 To lastColNK2)

    ' Gán d? li?u vào m?ng output
    outRow = 1
    For i = 2 To UBound(dataNK, 1) ' b?t d?u t? ḍng th? 2 trong m?ng (v́ ḍng 1 là tiêu d?)
        For j = 1 To lastColNK2
            If colMap(j) > 0 Then
                output(outRow, j) = dataNK(i, colMap(j))
            End If
        Next j
        outRow = outRow + 1
    Next i

    ' Ghi d? li?u t? m?ng ra sheet NK2
    wsNK2.Range("A5").Resize(UBound(output, 1), UBound(output, 2)).Value = output
 Application.ScreenUpdating = True
Application.DisplayAlerts = True
Application.EnableEvents = True
Application.Calculation = xlCalculationAutomatic
Call protected

End Sub
